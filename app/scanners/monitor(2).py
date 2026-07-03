"""
Мониторинг новых листингов Portals Market.

Диапазон цен: 50–450 TON
Наценка к флору: 0–20%
Уведомления в Telegram с фото подарка.
"""

import os
import argparse
import asyncio
import json
import logging
from typing import List, Optional, Any
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from html import escape

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

SESSION_NAME = "portals_account"
AUTO_REFRESH_AUTH = os.getenv("AUTO_REFRESH_AUTH", "0").lower() in {"1", "true", "yes", "on"}

CHECK_INTERVAL = 15

MIN_PRICE = 50
MAX_PRICE = 450
MAX_MARKUP_PCT = 20.0

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


def load_found_listings() -> list[dict[str, Any]]:
    if not FOUND_FILE.exists():
        return []

    try:
        with open(FOUND_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, list) else []

    except json.JSONDecodeError as e:
        backup_file = FOUND_FILE.with_suffix(".broken.json")
        FOUND_FILE.replace(backup_file)
        logger.warning(f"⚠️ found_listings.json повреждён, перенёс в {backup_file}: {e}")
        return []


def listing_key(listing: Listing) -> str:
    return f"{listing.source}:{listing.gift_id}:{listing.listed_at}:{listing.price}"


def save_listing(listing: Listing) -> None:
    try:
        data = load_found_listings()
        existing_keys = {
            f"{item.get('source')}:"
            f"{item.get('gift_id')}:"
            f"{item.get('listed_at')}:"
            f"{item.get('price')}"
            for item in data
            if isinstance(item, dict)
        }

        if listing_key(listing) in existing_keys:
            logger.debug(f"⏭️ Листинг уже сохранён: {listing.gift_id}")
            return

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

            date_str = escape(listing.listed_at[:10]) if listing.listed_at else "—"
            name = escape(listing.name)
            model = escape(listing.model)
            backdrop = escape(listing.backdrop)
            symbol = escape(listing.symbol)

            attrs = []

            if listing.model:
                attrs.append(
                    f"🏷️ <b>Модель:</b> {model} ({listing.model_rarity:.2f}%)"
                )

            if listing.backdrop:
                attrs.append(
                    f"🖼️ <b>Фон:</b> {backdrop} ({listing.backdrop_rarity:.2f}%)"
                )

            if listing.symbol:
                attrs.append(
                    f"🔣 <b>Символ:</b> {symbol} ({listing.symbol_rarity:.2f}%)"
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
                f"📦 <b>Название:</b> {name}\n"
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
                    timeout = aiohttp.ClientTimeout(total=10)
                    async with aiohttp.ClientSession(timeout=timeout) as session:
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
    def __init__(self, bot: TelegramBot, *, auto_refresh_auth: bool = AUTO_REFRESH_AUTH):
        self._bot = bot
        self._auto_refresh_auth = auto_refresh_auth
        self._auth: Optional[str] = self._load_auth()
        self._last_cursor: Optional[str] = self._load_state()

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
            if not self._auto_refresh_auth:
                raise RuntimeError(
                    "auth.txt не найден. Автоматическое создание/обновление Pyrogram-сессии отключено. "
                    "Сначала скопируй рабочий auth.txt на сервер или запусти: "
                    "python -m app.tools.monitor_terminal_control refresh-auth"
                )

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

    def _save_state(self, cursor: str) -> None:
        PORTALS_STATE_FILE.write_text(cursor, encoding="utf-8")

    @staticmethod
    def _activity_cursor(activity) -> str:
        gift = getattr(activity, "nft", None)
        gift_id = getattr(gift, "id", "") or ""
        created_at = getattr(activity, "created_at", "") or ""
        return f"{created_at}|{gift_id}"

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
            first_cursor: Optional[str] = None

            for activity in activities:
                created_at = activity.created_at or ""
                cursor = self._activity_cursor(activity)

                # Поддержка старого формата состояния, где хранился только created_at.
                if cursor == self._last_cursor or created_at == self._last_cursor:
                    break

                if activity.type != "listing":
                    continue

                new_activities.append(activity)

                if first_cursor is None:
                    first_cursor = cursor

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

            if first_cursor:
                self._last_cursor = first_cursor
                self._save_state(first_cursor)

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


def build_filters_str() -> str:
    filters = []

    if GIFT_NAME:
        filters.append(f"gift={GIFT_NAME!r}")

    if MODEL:
        filters.append(f"model={MODEL!r}")

    if BACKDROP:
        filters.append(f"backdrop={BACKDROP!r}")

    if SYMBOL:
        filters.append(f"symbol={SYMBOL!r}")

    return ", ".join(filters) if filters else "нет"


def log_startup_header(command: str) -> None:
    logger.info("=" * 55)
    logger.info("🚀 МОНИТОРИНГ PORTALS MARKET")
    logger.info("=" * 55)
    logger.info(f"▶️  Команда:    {command}")
    logger.info(f"⏱️  Интервал:  {CHECK_INTERVAL} сек")
    logger.info(f"💰 Цена:      {MIN_PRICE} – {MAX_PRICE} TON")
    logger.info(f"📈 Наценка:   до {MAX_MARKUP_PCT}% к флору")
    logger.info(f"🔍 Фильтры:   {build_filters_str()}")
    logger.info(f"📱 Уведомл.:  {'ВКЛЮЧЕНЫ' if USE_NOTIFICATIONS else 'ВЫКЛЮЧЕНЫ'}")
    logger.info(f"🔐 Auth file: {PORTALS_AUTH_FILE}")
    logger.info(f"🔁 Auto auth: {'ВКЛЮЧЁН' if AUTO_REFRESH_AUTH else 'ВЫКЛЮЧЕН'}")
    logger.info("=" * 55)


async def run_start() -> None:
    bot = TelegramBot()
    portals = PortalsMonitor(bot, auto_refresh_auth=AUTO_REFRESH_AUTH)

    log_startup_header("start")

    if USE_NOTIFICATIONS:
        await bot.send_text(
            "🚀 <b>Мониторинг Portals запущен вручную!</b>\n\n"
            f"⏱️ Интервал: {CHECK_INTERVAL} сек\n"
            f"💰 Цена: {MIN_PRICE} – {MAX_PRICE} TON\n"
            f"📈 Наценка к флору: до {MAX_MARKUP_PCT}%\n"
            f"🔍 Фильтры: {build_filters_str()}"
        )

    try:
        await portals.run()

    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("⏹️ Остановка...")

    finally:
        await bot.close()
        logger.info("👋 Завершено")


async def run_once() -> None:
    bot = TelegramBot()
    portals = PortalsMonitor(bot, auto_refresh_auth=AUTO_REFRESH_AUTH)

    log_startup_header("once")

    try:
        listings = await portals.check()
        logger.info(f"✅ Проверка завершена. Найдено подходящих листингов: {len(listings)}")

        for listing in listings:
            await bot.send_listing(listing)
            save_listing(listing)

    finally:
        await bot.close()


async def run_refresh_auth() -> None:
    bot = TelegramBot()
    portals = PortalsMonitor(bot, auto_refresh_auth=True)

    logger.info("🔄 Ручное обновление authData Portals")
    await portals._refresh_auth()
    await bot.close()
    logger.info("✅ auth.txt обновлён. Мониторинг не запущен.")


def print_status() -> None:
    logger.info("📋 Статус Portals Monitor")
    logger.info(f"Auth file:   {PORTALS_AUTH_FILE} — {'есть' if PORTALS_AUTH_FILE.exists() else 'нет'}")
    logger.info(f"State file:  {PORTALS_STATE_FILE} — {'есть' if PORTALS_STATE_FILE.exists() else 'нет'}")
    logger.info(f"Found file:  {FOUND_FILE} — {'есть' if FOUND_FILE.exists() else 'нет'}")
    logger.info(f"Tools dir:   {TOOLS_DIR}")
    logger.info(f"Auto auth:   {'on' if AUTO_REFRESH_AUTH else 'off'}")
    logger.info("Мониторинг не запущен. Для запуска: python -m app.tools.monitor_terminal_control start")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Portals Market monitor. По умолчанию ничего не запускает."
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="status",
        choices=["status", "start", "once", "refresh-auth"],
        help=(
            "status — показать состояние и выйти; "
            "start — запустить постоянный мониторинг; "
            "once — выполнить одну проверку; "
            "refresh-auth — вручную обновить auth.txt через Pyrogram"
        ),
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    if args.command == "status":
        print_status()
        return

    if args.command == "start":
        await run_start()
        return

    if args.command == "once":
        await run_once()
        return

    if args.command == "refresh-auth":
        await run_refresh_auth()
        return


if __name__ == "__main__":
    asyncio.run(main())