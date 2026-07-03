"""
Мониторинг новых листингов Portals Market.

Диапазон цен: 50–450 TON
Наценка к флору: 0–20%
Уведомления в Telegram с фото подарка.
"""

import os
import sys
import asyncio
import json
import logging
from typing import List, Optional
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field

from dotenv import load_dotenv

from aportalsmp.gifts import marketActivity
from aportalsmp.auth import update_auth
from aportalsmp.classes.Exceptions import (
    authDataError,
    requestError,
    connectionError,
    giftsError,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("monitor")
log_portals = logging.getLogger("portals")

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
TOOLS_DIR.mkdir(parents=True, exist_ok=True)

PORTALS_AUTH_FILE = TOOLS_DIR / "auth.txt"
PORTALS_STATE_FILE = TOOLS_DIR / "portals_last_created_at.txt"
FOUND_FILE = TOOLS_DIR / "found_listings.json"

SESSION_NAME = os.getenv("SESSION_NAME", "portals_account")
SESSION_FILE = TOOLS_DIR / f"{SESSION_NAME}.session"

CHECK_INTERVAL = 15

MIN_PRICE = 50
MAX_PRICE = 450
MAX_MARKUP_PCT = 300.0

GIFT_NAME: str | list = ""
MODEL: str | list = ""
BACKDROP: str | list = ""
SYMBOL: str | list = ""

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("ADMIN_ID", "")
USE_NOTIFICATIONS = bool(BOT_TOKEN and CHAT_ID)

API_ID = os.getenv("API_ID", "")
API_HASH = os.getenv("API_HASH", "")

PORTALS_REF = "qzuxyhlh"


def build_portals_url(nft_id: str) -> str:
    return f"https://t.me/portals_market_bot/market?startapp=gift_{nft_id}_{PORTALS_REF}"


def ensure_session_ready() -> None:
    """
    Проверяет наличие .session-файла ДО того, как Pyrogram попытается
    его использовать. Без этой проверки update_auth() на сервере без
    интерактивного stdin падает с 'EOF when reading a line', пытаясь
    запросить номер телефона.

    Сессия должна быть создана локально (create_session.py) и загружена
    на сервер в TOOLS_DIR вручную — скрипт сам её никогда не создаёт.
    """
    if not SESSION_FILE.exists():
        logger.error("=" * 55)
        logger.error("❌ Файл сессии не найден: %s", SESSION_FILE)
        logger.error("   Сгенерируйте его локально: python create_session.py")
        logger.error("   Затем загрузите файл '%s.session' в папку tools/ на сервере", SESSION_NAME)
        logger.error("=" * 55)
        sys.exit(1)

    logger.info("✅ Сессия найдена: %s", SESSION_FILE.name)


@dataclass
class Listing:
    source: str
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


def passes_markup_filter(price: float, floor_price: float) -> tuple[bool, float]:
    if floor_price <= 0:
        return True, 0.0

    markup = (price - floor_price) / floor_price * 100
    return markup <= MAX_MARKUP_PCT, markup


def save_listing(listing: Listing) -> None:
    try:
        data: list = []

        if FOUND_FILE.exists():
            with open(FOUND_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

        data.append(
            {
                "source": listing.source,
                "gift_id": listing.gift_id,
                "tg_id": listing.tg_id,
                "name": listing.name,
                "price": listing.price,
                "floor_price": listing.floor_price,
                "markup_pct": listing.markup_pct,
                "model": listing.model,
                "model_rarity": listing.model_rarity,
                "backdrop": listing.backdrop,
                "backdrop_rarity": listing.backdrop_rarity,
                "symbol": listing.symbol,
                "symbol_rarity": listing.symbol_rarity,
                "listed_at": listing.listed_at,
                "buy_url": listing.buy_url,
                "found_at": datetime.now().isoformat(),
            }
        )

        with open(FOUND_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.warning(f"⚠️ Не удалось сохранить листинг: {e}")


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
            import aiohttp
            from aiogram.types import (
                InlineKeyboardButton,
                InlineKeyboardMarkup,
                BufferedInputFile,
            )

            bot = await self.get()

            date_str = listing.listed_at[:10] if listing.listed_at else "—"

            attrs = []

            if listing.model:
                attrs.append(
                    f"🏷️ <b>Модель:</b> {listing.model} ({listing.model_rarity:.2f}%)"
                )

            if listing.backdrop:
                attrs.append(
                    f"🖼️ <b>Фон:</b> {listing.backdrop} ({listing.backdrop_rarity:.2f}%)"
                )

            if listing.symbol:
                attrs.append(
                    f"🔣 <b>Символ:</b> {listing.symbol} ({listing.symbol_rarity:.2f}%)"
                )

            attrs_str = "\n".join(attrs) if attrs else "—"

            floor_str = (
                f"{listing.floor_price:.2f} TON ({listing.markup_pct:+.1f}% к флору)"
                if listing.floor_price > 0
                else "—"
            )

            caption = (
                f"🔵 <b>Новый листинг — Portals Market!</b>\n\n"
                f"🔢 <b>Номер:</b> #{listing.tg_id}\n"
                f"📦 <b>Название:</b> {listing.name}\n"
                f"💰 <b>Цена:</b> {listing.price:.2f} TON\n"
                f"📊 <b>Флор:</b> {floor_str}\n"
                f"🕐 <b>Дата:</b> {date_str}\n\n"
                f"{attrs_str}"
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🛒 Купить",
                            url=listing.buy_url,
                        )
                    ]
                ]
            )

            if listing.photo_url:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(listing.photo_url) as response:
                            if response.status == 200:
                                photo_data = await response.read()

                                photo_file = BufferedInputFile(
                                    photo_data,
                                    filename=f"{listing.gift_id}.jpg",
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
                    logger.warning(f"⚠️ Не удалось отправить фото, fallback на текст: {e}")

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


class PortalsMonitor:
    def __init__(self, bot: TelegramBot):
        self._bot = bot
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
        log_portals.info("🔄 Обновляю authData Portals...")

        if not API_ID or not API_HASH:
            raise RuntimeError("Укажи API_ID и API_HASH в .env")

        auth = await update_auth(
            api_id=int(API_ID),
            api_hash=API_HASH,
            session_path=str(TOOLS_DIR),
            session_name=SESSION_NAME,
        )

        PORTALS_AUTH_FILE.write_text(auth, encoding="utf-8")
        log_portals.info("✅ authData Portals сохранён")

        return auth

    async def _get_auth(self) -> str:
        if not self._auth:
            self._auth = await self._refresh_auth()

        return self._auth

    def _invalidate_auth(self) -> None:
        self._auth = None
        PORTALS_AUTH_FILE.unlink(missing_ok=True)
        log_portals.warning("⚠️ Кэш authData Portals сброшен")

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
                    gift = activity.nft
                    price = float(activity.amount) if activity.amount else 0.0
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
                        backdrop_rarity=float(gift.backdrop_rarity)
                        if gift.backdrop_rarity
                        else 0.0,
                        symbol=gift.symbol or "",
                        symbol_rarity=float(gift.symbol_rarity)
                        if gift.symbol_rarity
                        else 0.0,
                        listed_at=activity.created_at or "",
                        photo_url=gift.photo_url or "",
                        buy_url=build_portals_url(gift.id),
                    )

                    listings.append(listing)

                    log_portals.info(
                        f"🎁 #{listing.tg_id} {listing.name} | "
                        f"{listing.price:.2f} TON "
                        f"(floor {listing.floor_price:.2f}, {markup:+.1f}%)"
                    )

                except Exception as e:
                    log_portals.error(f"❌ Ошибка обработки листинга: {e}")
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


async def main() -> None:
    ensure_session_ready()

    bot = TelegramBot()
    portals = PortalsMonitor(bot)

    filters = []

    if GIFT_NAME:
        filters.append(f"gift={GIFT_NAME!r}")

    if MODEL:
        filters.append(f"model={MODEL!r}")

    if BACKDROP:
        filters.append(f"backdrop={BACKDROP!r}")

    if SYMBOL:
        filters.append(f"symbol={SYMBOL!r}")

    filters_str = ", ".join(filters) if filters else "нет"

    logger.info("=" * 55)
    logger.info("🚀 МОНИТОРИНГ PORTALS MARKET")
    logger.info("=" * 55)
    logger.info(f"⏱️  Интервал:  {CHECK_INTERVAL} сек")
    logger.info(f"💰 Цена:      {MIN_PRICE} – {MAX_PRICE} TON")
    logger.info(f"📈 Наценка:   0 – {MAX_MARKUP_PCT}% к флору")
    logger.info(f"🔍 Фильтры:   {filters_str}")
    logger.info(f"📱 Уведомл.:  {'ВКЛЮЧЕНЫ' if USE_NOTIFICATIONS else 'ВЫКЛЮЧЕНЫ'}")
    logger.info("=" * 55)

    if USE_NOTIFICATIONS:
        await bot.send_text(
            "🚀 <b>Мониторинг Portals запущен!</b>\n\n"
            f"⏱️ Интервал: {CHECK_INTERVAL} сек\n"
            f"💰 Цена: {MIN_PRICE} – {MAX_PRICE} TON\n"
            f"📈 Наценка к флору: 0 – {MAX_MARKUP_PCT}%\n"
            f"🔍 Фильтры: {filters_str}"
        )

    try:
        await portals.run()

    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("⏹️ Остановка...")

    finally:
        await bot.close()
        logger.info("👋 Завершено")


if __name__ == "__main__":
    asyncio.run(main())