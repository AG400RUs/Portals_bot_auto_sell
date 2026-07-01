"""
Параллельный мониторинг новых листингов на двух площадках:
  • Portals Market (через aportalsmp)
  • MRKT          (через прямые HTTP-запросы к api.tgmrkt.io)

Диапазон цен: 50–300 TON, наценка к флору: 0–20%
Уведомления в Telegram.
"""

import os
import asyncio
import json
import logging
from typing import List, Optional
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from urllib.parse import unquote

from dotenv import load_dotenv

# ── Portals ───────────────────────────────────────────────────────────
from aportalsmp.gifts import marketActivity
from aportalsmp.auth import update_auth
from aportalsmp.classes.Exceptions import (
    authDataError, requestError, connectionError, giftsError,
)

# ── MRKT (прямые запросы) ─────────────────────────────────────────────
from curl_cffi import AsyncSession
from pyrogram import Client
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw.types import InputBotAppShortName, InputUser

# ===== ЗАГРУЗКА ПЕРЕМЕННЫХ =====
load_dotenv()

# ===== ГЛОБАЛЬНЫЙ LOCK ДЛЯ PYROGRAM =====
# Один .session файл (SQLite) не может открываться двумя клиентами одновременно.
# Все операции с Pyrogram идут строго последовательно через этот lock.
PYROGRAM_LOCK: asyncio.Lock  # инициализируется в main()

# ===== ЛОГГИРОВАНИЕ =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S',
)
logger      = logging.getLogger("monitor")
log_portals = logging.getLogger("portals")
log_mrkt    = logging.getLogger("mrkt")

# ===== ПУТИ =====
BASE_DIR  = Path(__file__).resolve().parent.parent
TOOLS_DIR = BASE_DIR / "tools"
TOOLS_DIR.mkdir(parents=True, exist_ok=True)

PORTALS_AUTH_FILE  = TOOLS_DIR / "portals_auth.txt"
PORTALS_STATE_FILE = TOOLS_DIR / "portals_last_created_at.txt"
MRKT_TOKEN_FILE    = TOOLS_DIR / "mrkt_token.txt"
MRKT_STATE_FILE    = TOOLS_DIR / "mrkt_seen_ids.json"
FOUND_FILE         = TOOLS_DIR / "found_listings.json"

# ===== ОБЩИЕ НАСТРОЙКИ =====
CHECK_INTERVAL = 15       # секунды между циклами каждого монитора
MIN_PRICE      = 50       # TON
MAX_PRICE      = 450      # TON
MAX_MARKUP_PCT = 20.0     # максимальная наценка к флору в %

# ===== ФИЛЬТРЫ (пустое = без фильтра) =====
GIFT_NAME: str | list = ""
MODEL:     str | list = ""
BACKDROP:  str | list = ""
SYMBOL:    str | list = ""

# ===== TELEGRAM =====
BOT_TOKEN         = os.getenv("BOT_TOKEN", "")
CHAT_ID           = os.getenv("ADMIN_ID", "")
USE_NOTIFICATIONS = bool(BOT_TOKEN and CHAT_ID)

# ===== АВТОРИЗАЦИЯ TELEGRAM =====
API_ID       = os.getenv("API_ID", "")
API_HASH     = os.getenv("API_HASH", "")
SESSION_NAME = os.getenv("SESSION_NAME", "portals_account")

# ===== РЕФЕРАЛЬНЫЕ ССЫЛКИ =====
PORTALS_REF = "qzuxyhlh"
MRKT_API    = "https://api.tgmrkt.io/api/v1"


def build_portals_url(nft_id: str) -> str:
    return f"https://t.me/portals_market_bot/market?startapp=gift_{nft_id}_{PORTALS_REF}"


def build_mrkt_url(gift_id: str) -> str:
    return f"https://t.me/mrkt/app?startapp=gift_{gift_id}"


# ═════════════════════════════════════════════════════════════════════
# Общая модель листинга
# ═════════════════════════════════════════════════════════════════════

@dataclass
class Listing:
    source: str           # "portals" | "mrkt"
    gift_id: str
    tg_id: int
    name: str
    price: float
    floor_price: float
    markup_pct: float
    model: str
    model_rarity: float
    backdrop: str
    backdrop_rarity: float
    symbol: str
    symbol_rarity: float
    listed_at: str
    photo_url: str
    buy_url: str = field(default="")


# ═════════════════════════════════════════════════════════════════════
# Утилиты
# ═════════════════════════════════════════════════════════════════════

def passes_markup_filter(price: float, floor_price: float) -> tuple[bool, float]:
    """Возвращает (прошёл_фильтр, наценка_%). floor_price==0 → пропускаем."""
    if floor_price <= 0:
        return True, 0.0
    markup = (price - floor_price) / floor_price * 100
    return markup <= MAX_MARKUP_PCT, markup


def save_listing(listing: Listing) -> None:
    try:
        data: list = []
        if FOUND_FILE.exists():
            with open(FOUND_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        data.append({
            "source":          listing.source,
            "gift_id":         listing.gift_id,
            "tg_id":           listing.tg_id,
            "name":            listing.name,
            "price":           listing.price,
            "floor_price":     listing.floor_price,
            "markup_pct":      listing.markup_pct,
            "model":           listing.model,
            "model_rarity":    listing.model_rarity,
            "backdrop":        listing.backdrop,
            "backdrop_rarity": listing.backdrop_rarity,
            "symbol":          listing.symbol,
            "symbol_rarity":   listing.symbol_rarity,
            "listed_at":       listing.listed_at,
            "buy_url":         listing.buy_url,
            "found_at":        datetime.now().isoformat(),
        })
        with open(FOUND_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"⚠️ Не удалось сохранить листинг: {e}")


# ═════════════════════════════════════════════════════════════════════
# Telegram-бот (singleton, общий для обоих мониторов)
# ═════════════════════════════════════════════════════════════════════

class TelegramBot:
    def __init__(self):
        self._bot = None

    async def get(self):
        if self._bot is None:
            from aiogram import Bot
            self._bot = Bot(token=BOT_TOKEN)
        return self._bot

    async def close(self) -> None:
        if self._bot is not None:
            try:
                await self._bot.session.close()
                logger.info("🔒 Сессия Telegram-бота закрыта")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка закрытия сессии бота: {e}")
            finally:
                self._bot = None

    async def send_listing(self, listing: Listing) -> bool:
        if not USE_NOTIFICATIONS:
            return False
        try:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            from aiogram.types import InputMediaPhoto
            from aiogram import Bot
            import aiohttp

            bot = await self.get()

            # ── Формируем подпись (caption) ──
            source_emoji = "🔵" if listing.source == "portals" else "🟣"
            source_name = "Portals Market" if listing.source == "portals" else "MRKT"
            date_str = listing.listed_at[:10] if listing.listed_at else "—"

            attrs = []
            if listing.model:
                attrs.append(f"🏷️ <b>Модель:</b> {listing.model} ({listing.model_rarity:.2f}%)")
            if listing.backdrop:
                attrs.append(f"🖼️ <b>Фон:</b> {listing.backdrop} ({listing.backdrop_rarity:.2f}%)")
            if listing.symbol:
                attrs.append(f"🔣 <b>Символ:</b> {listing.symbol} ({listing.symbol_rarity:.2f}%)")
            attrs_str = "\n".join(attrs) if attrs else "—"

            floor_str = (
                f"{listing.floor_price} TON ({listing.markup_pct:+.1f}% к флору)"
                if listing.floor_price > 0 else "—"
            )

            caption = (
                f"{source_emoji} <b>Новый листинг — {source_name}!</b>\n\n"
                f"🔢 <b>Номер:</b> #{listing.tg_id}\n"
                f"📦 <b>Название:</b> {listing.name}\n"
                f"💰 <b>Цена:</b> {listing.price} TON\n"
                f"📊 <b>Флор:</b> {floor_str}\n"
                f"🕐 <b>Дата:</b> {date_str}\n\n"
                f"{attrs_str}"
            )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🛒 Купить", url=listing.buy_url)
            ]])

            # ── Пробуем отправить с фото ──
            if listing.photo_url:
                try:
                    # Скачиваем фото в память
                    async with aiohttp.ClientSession() as session:
                        async with session.get(listing.photo_url) as resp:
                            if resp.status == 200:
                                photo_data = await resp.read()
                                # Отправляем как InputFile из байтов
                                from aiogram.types import BufferedInputFile
                                photo_file = BufferedInputFile(
                                    photo_data,
                                    filename=f"{listing.gift_id}.jpg"
                                )
                                await bot.send_photo(
                                    chat_id=CHAT_ID,
                                    photo=photo_file,
                                    caption=caption,
                                    parse_mode="HTML",
                                    reply_markup=keyboard,
                                )
                                return True
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось отправить фото: {e}")
                    # Падаем через отправку без фото

            # ── Fallback: без фото ──
            await bot.send_message(
                chat_id=CHAT_ID,
                text=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=False,
            )
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления: {e}")
            return False
    async def send_text(self, text: str) -> None:
        if not USE_NOTIFICATIONS:
            return
        try:
            bot = await self.get()
            await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки текста: {e}")


# ═════════════════════════════════════════════════════════════════════
# PORTALS MONITOR
# ═════════════════════════════════════════════════════════════════════

class PortalsMonitor:
    def __init__(self, bot: TelegramBot):
        self._bot  = bot
        self._auth: Optional[str] = self._load_auth()
        self._last_created_at: Optional[str] = self._load_state()

    def _load_auth(self) -> Optional[str]:
        if PORTALS_AUTH_FILE.exists():
            data = PORTALS_AUTH_FILE.read_text(encoding="utf-8").strip()
            if data:
                log_portals.info(f"📂 authData загружен из кэша ({len(data)} символов)")
                return data
        return None

    async def _refresh_auth(self) -> str:
        log_portals.info("🔄 Обновляю authData (Portals)...")
        if not API_ID or not API_HASH:
            raise RuntimeError("Укажи API_ID и API_HASH в .env")
        async with PYROGRAM_LOCK:
            log_portals.info("🔒 Захватываю PYROGRAM_LOCK (Portals)")
            auth = await update_auth(
                api_id=int(API_ID),
                api_hash=API_HASH,
                session_path=str(TOOLS_DIR),
                session_name=SESSION_NAME,
            )
        PORTALS_AUTH_FILE.write_text(auth, encoding="utf-8")
        log_portals.info("✅ authData (Portals) сохранён")
        return auth

    async def _get_auth(self) -> str:
        if not self._auth:
            self._auth = await self._refresh_auth()
        return self._auth

    def _invalidate_auth(self) -> None:
        self._auth = None
        PORTALS_AUTH_FILE.unlink(missing_ok=True)
        log_portals.warning("⚠️ Кэш authData (Portals) сброшен")

    def _load_state(self) -> Optional[str]:
        if PORTALS_STATE_FILE.exists():
            data = PORTALS_STATE_FILE.read_text(encoding="utf-8").strip()
            if data:
                log_portals.info(f"📂 Курсор Portals: {data}")
                return data
        return None

    def _save_state(self, created_at: str) -> None:
        PORTALS_STATE_FILE.write_text(created_at, encoding="utf-8")

    async def check(self) -> List[Listing]:
        try:
            auth = await self._get_auth()

            activities = await marketActivity(
                authData=auth,
                sort="latest",
                offset=0,
                limit=100,
                activityType="listing",
                gift_name=GIFT_NAME,
                model=MODEL,
                backdrop=BACKDROP,
                symbol=SYMBOL,
                min_price=MIN_PRICE,
                max_price=MAX_PRICE,
            )

            if not activities:
                return []

            new_activities = []
            first_created_at: Optional[str] = None

            for activity in activities:
                created_at = activity.created_at
                if created_at == self._last_created_at:
                    break
                if activity.type != "listing":
                    continue
                new_activities.append(activity)
                if first_created_at is None:
                    first_created_at = created_at

            if not new_activities:
                return []

            log_portals.info(f"📦 Новых листингов: {len(new_activities)}")
            listings = []

            for activity in new_activities:
                try:
                    gift        = activity.nft
                    price       = float(activity.amount) if activity.amount else 0.0
                    floor_price = float(gift.floor_price) if gift.floor_price else 0.0

                    ok, markup = passes_markup_filter(price, floor_price)
                    if not ok:
                        log_portals.debug(
                            f"⏭️ Пропускаю #{gift.tg_id} {gift.name} — наценка {markup:.1f}%"
                        )
                        continue

                    listing = Listing(
                        source="portals",
                        gift_id=gift.id,
                        tg_id=gift.tg_id,
                        name=gift.name,
                        price=price,
                        floor_price=floor_price,
                        markup_pct=markup,
                        model=gift.model or "",
                        model_rarity=float(gift.model_rarity) if gift.model_rarity else 0.0,
                        backdrop=gift.backdrop or "",
                        backdrop_rarity=float(gift.backdrop_rarity) if gift.backdrop_rarity else 0.0,
                        symbol=gift.symbol or "",
                        symbol_rarity=float(gift.symbol_rarity) if gift.symbol_rarity else 0.0,
                        listed_at=activity.created_at or "",
                        photo_url=gift.photo_url or "",
                        buy_url=build_portals_url(gift.id),
                    )
                    listings.append(listing)
                    log_portals.info(
                        f"🎁 #{listing.tg_id} {listing.name} | "
                        f"{listing.price} TON (floor {listing.floor_price}, {markup:+.1f}%)"
                    )

                except Exception as e:
                    log_portals.error(f"❌ Ошибка обработки: {e}")
                    continue

            if first_created_at:
                self._last_created_at = first_created_at
                self._save_state(first_created_at)

            return listings

        except authDataError as e:
            log_portals.error(f"❌ Ошибка авторизации: {e}")
            self._invalidate_auth()
            return []
        except giftsError as e:
            log_portals.error(f"❌ Ошибка параметров: {e}")
            return []
        except (requestError, connectionError) as e:
            err = str(e)
            if "401" in err or "auth sign is invalid" in err:
                log_portals.warning("🔑 Токен Portals протух — сбрасываю...")
                self._invalidate_auth()
            else:
                log_portals.error(f"❌ Ошибка соединения: {e}")
            return []
        except Exception as e:
            log_portals.error(f"❌ Непредвиденная ошибка: {e}")
            return []

    async def run(self) -> None:
        log_portals.info("🔵 Portals Monitor запущен")
        while True:
            try:
                for listing in await self.check():
                    await self._bot.send_listing(listing)
                    save_listing(listing)
            except Exception as e:
                log_portals.error(f"❌ Ошибка в цикле: {e}")
            await asyncio.sleep(CHECK_INTERVAL)


# ═════════════════════════════════════════════════════════════════════
# MRKT MONITOR
# ═════════════════════════════════════════════════════════════════════

class MrktMonitor:
    def __init__(self, bot: TelegramBot):
        self._bot   = bot
        self._token: Optional[str] = self._load_token()
        self._seen_ids: set[str]   = self._load_state()

    def _load_token(self) -> Optional[str]:
        if MRKT_TOKEN_FILE.exists():
            data = MRKT_TOKEN_FILE.read_text(encoding="utf-8").strip()
            if data:
                log_mrkt.info("📂 MRKT токен загружен из кэша")
                return data
        return None

    async def _refresh_token(self) -> str:
        log_mrkt.info("🔄 Получаю новый MRKT токен...")
        if not API_ID or not API_HASH:
            raise RuntimeError("Укажи API_ID и API_HASH в .env")

        session_path = TOOLS_DIR / f"{SESSION_NAME}.session"
        if not session_path.exists():
            raise FileNotFoundError(f"Сессия не найдена: {session_path}")

        async with PYROGRAM_LOCK:
            log_mrkt.info("🔒 Захватываю PYROGRAM_LOCK (MRKT)")
            client = Client(
                name=SESSION_NAME,
                api_id=int(API_ID),
                api_hash=API_HASH,
                workdir=str(TOOLS_DIR),
                in_memory=False,
            )
            try:
                await client.start()
                peer       = await client.resolve_peer("mrkt")
                # resolve_peer возвращает низкоуровневый InputPeerUser с access_hash
                bot        = InputUser(
                    user_id=peer.user_id,
                    access_hash=peer.access_hash,
                )
                web_view = await client.invoke(
                    RequestAppWebView(
                        peer=peer,
                        app=InputBotAppShortName(bot_id=bot, short_name="app"),
                        platform="android",
                    )
                )
                init_data = unquote(
                    web_view.url.split("tgWebAppData=", 1)[1]
                               .split("&tgWebAppVersion", 1)[0]
                )
                async with AsyncSession() as s:
                    r     = await s.post(f"{MRKT_API}/auth", json={"data": init_data})
                    rj    = r.json()
                    token = rj.get("token")
                    if not token:
                        raise RuntimeError(f"MRKT /auth не вернул токен: {rj}")

                MRKT_TOKEN_FILE.write_text(token, encoding="utf-8")
                log_mrkt.info("✅ MRKT токен сохранён")
                return token

            finally:
                await client.stop()

    async def _get_token(self) -> str:
        if not self._token:
            self._token = await self._refresh_token()
        return self._token

    def _invalidate_token(self) -> None:
        self._token = None
        MRKT_TOKEN_FILE.unlink(missing_ok=True)
        log_mrkt.warning("⚠️ Кэш MRKT токена сброшен")

    def _load_state(self) -> set[str]:
        if MRKT_STATE_FILE.exists():
            try:
                data = json.loads(MRKT_STATE_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return set(data)
            except Exception:
                pass
        return set()

    def _save_state(self) -> None:
        try:
            ids = list(self._seen_ids)[-500:]   # не даём файлу расти бесконечно
            MRKT_STATE_FILE.write_text(json.dumps(ids, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            log_mrkt.warning(f"⚠️ Не удалось сохранить state MRKT: {e}")

    @staticmethod
    def _calc_floor(gifts: list) -> dict[str, float]:
        """MRKT не отдаёт floor_price — считаем минимум salePrice по коллекции из выборки."""
        floors: dict[str, float] = {}
        for g in gifts:
            name = g.get("collectionName", "")
            try:
                price = float(g.get("salePrice") or 0) / 1_000_000_000  # наноTON → TON
            except (TypeError, ValueError):
                continue
            if price > 0 and (name not in floors or price < floors[name]):
                floors[name] = price
        return floors

    def _to_filter_list(self, value: str | list) -> list:
        if not value:
            return []
        return [value] if isinstance(value, str) else list(value)

    async def _fetch_gifts(self, token: str) -> list:
        headers = {"Authorization": token, "Referer": "https://cdn.tgmrkt.io/"}
        # MRKT использует наноTON (1 TON = 1_000_000_000 наноTON)
        NANO = 1_000_000_000
        payload = {
            "collectionNames": self._to_filter_list(GIFT_NAME),
            "modelNames":      self._to_filter_list(MODEL),
            "backdropNames":   self._to_filter_list(BACKDROP),
            "symbolNames":     self._to_filter_list(SYMBOL),
            "ordering":        "Price",
            "lowToHigh":       True,
            "maxPrice":        MAX_PRICE * NANO,
            "minPrice":        MIN_PRICE * NANO,
            "mintable":        None,
            "number":          None,
            "count":           20,
            "cursor":          "",
            "query":           None,
            "promotedFirst":   False,
        }
        async with AsyncSession() as s:
            r  = await s.post(f"{MRKT_API}/gifts/saling", headers=headers, json=payload)
            rj = r.json()
            log_mrkt.debug(f"MRKT response: status={r.status_code} body={str(rj)[:300]}")
            return rj.get("gifts", [])

    async def check(self) -> List[Listing]:
        try:
            token  = await self._get_token()
            gifts  = await self._fetch_gifts(token)

            if not gifts:
                return []

            floors   = self._calc_floor(gifts)
            listings = []
            new_ids: set[str] = set()

            for g in gifts:
                gift_id = str(g.get("id", ""))
                if not gift_id or gift_id in self._seen_ids:
                    continue
                new_ids.add(gift_id)

                name  = g.get("collectionName", "Без названия")
                tg_id = int(g.get("number") or 0)
                # salePrice в наноTON → конвертируем в TON
                try:
                    price = float(g.get("salePrice") or 0) / 1_000_000_000
                except (TypeError, ValueError):
                    price = 0.0

                floor_price = floors.get(name, 0.0)
                ok, markup  = passes_markup_filter(price, floor_price)

                if not ok:
                    log_mrkt.debug(
                        f"⏭️ Пропускаю #{tg_id} {name} — наценка {markup:.1f}%"
                    )
                    continue

                # Атрибуты — плоские поля, редкость в промилле (делим на 10 для %)
                listing = Listing(
                    source="mrkt",
                    gift_id=gift_id,
                    tg_id=tg_id,
                    name=name,
                    price=price,
                    floor_price=floor_price,
                    markup_pct=markup,
                    model=g.get("modelName", ""),
                    model_rarity=round(float(g.get("modelRarityPerMille") or 0) / 10, 2),
                    backdrop=g.get("backdropName", ""),
                    backdrop_rarity=round(float(g.get("backdropRarityPerMille") or 0) / 10, 2),
                    symbol=g.get("symbolName", ""),
                    symbol_rarity=round(float(g.get("symbolRarityPerMille") or 0) / 10, 2),
                    listed_at=g.get("receivedDate", ""),
                    photo_url="",
                    buy_url=build_mrkt_url(gift_id),
                )
                listings.append(listing)
                log_mrkt.info(
                    f"🎁 #{listing.tg_id} {listing.name} | "
                    f"{listing.price} TON (floor {listing.floor_price}, {markup:+.1f}%)"
                )

            self._seen_ids.update(new_ids)
            if new_ids:
                self._save_state()

            return listings

        except Exception as e:
            err = str(e)
            if "401" in err or "Unauthorized" in err:
                log_mrkt.warning("🔑 MRKT токен протух — сбрасываю...")
                self._invalidate_token()
            else:
                log_mrkt.error(f"❌ Ошибка MRKT: {e}")
            return []

    async def run(self) -> None:
        log_mrkt.info("🟣 MRKT Monitor запущен")
        while True:
            try:
                for listing in await self.check():
                    await self._bot.send_listing(listing)
                    save_listing(listing)
            except Exception as e:
                log_mrkt.error(f"❌ Ошибка в цикле: {e}")
            await asyncio.sleep(CHECK_INTERVAL)


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

async def main() -> None:
    global PYROGRAM_LOCK
    PYROGRAM_LOCK = asyncio.Lock()

    bot     = TelegramBot()
    portals = PortalsMonitor(bot)
    mrkt    = MrktMonitor(bot)

    filters = []
    if GIFT_NAME: filters.append(f"gift={GIFT_NAME!r}")
    if MODEL:     filters.append(f"model={MODEL!r}")
    if BACKDROP:  filters.append(f"backdrop={BACKDROP!r}")
    if SYMBOL:    filters.append(f"symbol={SYMBOL!r}")
    filters_str = ", ".join(filters) if filters else "нет"

    logger.info("=" * 55)
    logger.info("🚀 ПАРАЛЛЕЛЬНЫЙ МОНИТОРИНГ ЛИСТИНГОВ")
    logger.info("=" * 55)
    logger.info(f"⏱️  Интервал:  {CHECK_INTERVAL} сек")
    logger.info(f"💰 Цена:      {MIN_PRICE} – {MAX_PRICE} TON")
    logger.info(f"📈 Наценка:   0 – {MAX_MARKUP_PCT}% к флору")
    logger.info(f"🔍 Фильтры:  {filters_str}")
    logger.info(f"📱 Уведомл.: {'ВКЛЮЧЕНЫ' if USE_NOTIFICATIONS else 'ВЫКЛЮЧЕНЫ'}")
    logger.info("=" * 55)

    if USE_NOTIFICATIONS:
        await bot.send_text(
            "🚀 <b>Мониторинг запущен!</b>\n\n"
            "🔵 Portals Market\n"
            "🟣 MRKT\n\n"
            f"⏱️ Интервал: {CHECK_INTERVAL} сек\n"
            f"💰 Цена: {MIN_PRICE} – {MAX_PRICE} TON\n"
            f"📈 Наценка к флору: 0 – {MAX_MARKUP_PCT}%\n"
            f"🔍 Фильтры: {filters_str}"
        )

    try:
        await asyncio.gather(
            portals.run(),
            mrkt.run(),
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("⏹️ Остановка...")
    finally:
        await bot.close()
        logger.info("👋 Завершено")


if __name__ == "__main__":
    asyncio.run(main())