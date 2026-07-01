"""
Мониторинг новых листингов подарков в диапазоне 50–300 TON на Portals Market
Отправляет уведомления в Telegram при обнаружении
"""

import os
import asyncio
import json
import logging
from typing import List, Optional
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass

from dotenv import load_dotenv

from aportalsmp.gifts import marketActivity
from aportalsmp.auth import update_auth
from aportalsmp.classes.Exceptions import authDataError, requestError, connectionError, giftsError

# ===== ЗАГРУЗКА ПЕРЕМЕННЫХ =====
load_dotenv()

# ===== НАСТРОЙКА ЛОГГИРОВАНИЯ =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ===== ПУТИ =====
BASE_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = BASE_DIR / "tools"
AUTH_FILE = TOOLS_DIR / "auth.txt"
STATE_FILE = TOOLS_DIR / "last_listing_created_at.txt"
FOUND_FILE = TOOLS_DIR / "found_listings.json"

# ===== НАСТРОЙКИ ПОИСКА =====
CHECK_INTERVAL = 15       # секунды между проверками
MIN_PRICE = 50            # минимальная цена в TON
MAX_PRICE = 300           # максимальная цена в TON
FETCH_LIMIT = 100         # максимум по документации
MAX_MARKUP_PCT = 20.0    # максимальная наценка к флору в %

# Фильтры (пустая строка = без фильтра, можно передать список)
# Примеры:
#   GIFT_NAME = "Jelly Bunny"
#   MODEL = ["Silver", "Gold"]
GIFT_NAME: str | list = ""
MODEL:     str | list = ""
BACKDROP:  str | list = ""
SYMBOL:    str | list = ""

# ===== НАСТРОЙКИ ТЕЛЕГРАМ-БОТА =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("ADMIN_ID", "")
USE_NOTIFICATIONS = bool(BOT_TOKEN and CHAT_ID)

# ===== НАСТРОЙКИ АВТОРИЗАЦИИ =====
API_ID = os.getenv("API_ID", "")
API_HASH = os.getenv("API_HASH", "")
SESSION_NAME = os.getenv("SESSION_NAME", "account")

# ===== РЕФЕРАЛЬНАЯ ССЫЛКА =====
REFERRAL_CODE = "qzuxyhlh"


def build_portals_url(nft_id: str) -> str:
    return (
        f"https://t.me/portals_market_bot/market"
        f"?startapp=gift_{nft_id}_{REFERRAL_CODE}"
    )


@dataclass
class Listing:
    gift_id: str
    tg_id: int           # Telegram-номер подарка (external_collection_number)
    name: str
    price: float         # цена листинга (activity.amount)
    floor_price: float   # флор коллекции
    model: str
    model_rarity: float
    backdrop: str
    backdrop_rarity: float
    symbol: str
    symbol_rarity: float
    listed_at: str       # activity.created_at
    photo_url: str
    animation_url: str


class ListingMonitor:
    def __init__(self):
        self._auth: Optional[str] = self._load_auth()
        # Курсор — created_at последнего обработанного листинга (строка ISO)
        self._last_created_at: Optional[str] = self._load_state()
        self._bot = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _load_auth(self) -> Optional[str]:
        """Загружает кэшированный authData из файла."""
        if AUTH_FILE.exists():
            data = AUTH_FILE.read_text(encoding="utf-8").strip()
            if data:
                logger.info(f"📂 authData загружен из кэша ({len(data)} символов)")
                return data
        return None

    async def _refresh_auth(self) -> str:
        """
        Получает свежий authData через update_auth из библиотеки.
        Библиотека сама работает с Pyrogram — нам не нужен ручной код.
        """
        logger.info("🔄 Получаю новый authData через update_auth()...")

        if not API_ID or not API_HASH:
            raise RuntimeError("Укажи API_ID и API_HASH в .env файле")

        auth = await update_auth(
            api_id=int(API_ID),
            api_hash=API_HASH,
            session_path=str(TOOLS_DIR),
            session_name=SESSION_NAME,
        )

        AUTH_FILE.write_text(auth, encoding="utf-8")
        logger.info(f"✅ authData сохранён в {AUTH_FILE}")
        return auth

    async def _get_auth(self) -> str:
        """Возвращает актуальный authData, при необходимости обновляет."""
        if not self._auth:
            self._auth = await self._refresh_auth()
        return self._auth

    def _invalidate_auth(self) -> None:
        """Сбрасывает кэш авторизации при ошибке."""
        self._auth = None
        AUTH_FILE.unlink(missing_ok=True)
        logger.warning("⚠️ Кэш authData сброшен — при следующем цикле будет обновлён")

    # ------------------------------------------------------------------
    # State (курсор по created_at)
    # ------------------------------------------------------------------

    def _load_state(self) -> Optional[str]:
        if STATE_FILE.exists():
            try:
                data = STATE_FILE.read_text(encoding="utf-8").strip()
                if data:
                    logger.info(f"📂 Курсор загружен: {data}")
                    return data
            except Exception as e:
                logger.warning(f"⚠️ Не удалось загрузить state: {e}")
        return None

    def _save_state(self, created_at: str) -> None:
        try:
            STATE_FILE.write_text(created_at, encoding="utf-8")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось сохранить state: {e}")

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    async def check_new_listings(self) -> List[Listing]:
        try:
            auth = await self._get_auth()

            activities = await marketActivity(
                authData=auth,
                sort="latest",
                offset=0,
                limit=FETCH_LIMIT,
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

            # Собираем только новые активности.
            # Курсор — created_at: останавливаемся, когда встречаем уже виденную запись.
            new_activities = []
            first_created_at: Optional[str] = None

            for activity in activities:
                created_at = activity.created_at  # ISO строка

                if created_at == self._last_created_at:
                    break

                if activity.type != "listing":
                    continue

                new_activities.append(activity)

                if first_created_at is None:
                    first_created_at = created_at

            if not new_activities:
                return []

            logger.info(f"📦 Найдено {len(new_activities)} новых листингов")

            listings = []

            for activity in new_activities:
                try:
                    gift = activity.nft  # PortalsGift объект

                    listing = Listing(
                        gift_id=gift.id,
                        tg_id=gift.tg_id,
                        name=gift.name,
                        price=float(activity.amount) if activity.amount else 0.0,
                        floor_price=float(gift.floor_price) if gift.floor_price else 0.0,
                        model=gift.model or "",
                        model_rarity=float(gift.model_rarity) if gift.model_rarity else 0.0,
                        backdrop=gift.backdrop or "",
                        backdrop_rarity=float(gift.backdrop_rarity) if gift.backdrop_rarity else 0.0,
                        symbol=gift.symbol or "",
                        symbol_rarity=float(gift.symbol_rarity) if gift.symbol_rarity else 0.0,
                        listed_at=activity.created_at or "",
                        photo_url=gift.photo_url or "",
                        animation_url=gift.animation_url or "",
                    )
                    # Фильтр по наценке к флору
                    if listing.floor_price > 0:
                        markup_pct = (listing.price - listing.floor_price) / listing.floor_price * 100
                        if markup_pct > MAX_MARKUP_PCT:
                            logger.debug(
                                f"⏭️ Пропускаю #{listing.tg_id} {listing.name} — "
                                f"наценка {markup_pct:.1f}% > {MAX_MARKUP_PCT}%"
                            )
                            continue

                    markup_str = (
                        f"{((listing.price - listing.floor_price) / listing.floor_price * 100):+.1f}%"
                        if listing.floor_price > 0 else "флор неизвестен"
                    )
                    listings.append(listing)
                    logger.info(
                        f"🎁 #{listing.tg_id} {listing.name} | "
                        f"model={listing.model} ({listing.model_rarity}%) | "
                        f"{listing.price} TON (floor: {listing.floor_price}, {markup_str})"
                    )

                except Exception as e:
                    logger.error(f"❌ Ошибка обработки активности: {e}")
                    continue

            # Сохраняем курсор только после успешной обработки всего батча
            if first_created_at:
                self._last_created_at = first_created_at
                self._save_state(first_created_at)

            return listings

        except authDataError as e:
            logger.error(f"❌ Ошибка авторизации: {e}")
            self._invalidate_auth()
            return []
        except giftsError as e:
            logger.error(f"❌ Ошибка параметров запроса: {e}")
            return []
        except (requestError, connectionError) as e:
            err = str(e)
            if "401" in err or "auth sign is invalid" in err:
                logger.warning("🔑 Токен протух (401) — сбрасываю кэш и обновляю authData...")
                self._invalidate_auth()  # удаляет auth.txt, сбрасывает self._auth
            else:
                logger.error(f"❌ Ошибка соединения: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Непредвиденная ошибка: {e}")
            return []

    # ------------------------------------------------------------------
    # Telegram
    # ------------------------------------------------------------------

    async def _get_bot(self):
        if self._bot is None:
            from aiogram import Bot
            self._bot = Bot(token=BOT_TOKEN)
        return self._bot

    async def _close_bot(self) -> None:
        if self._bot is not None:
            try:
                await self._bot.session.close()
                logger.info("🔒 Сессия Telegram-бота закрыта")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при закрытии сессии бота: {e}")
            finally:
                self._bot = None

    async def send_notification(self, listing: Listing) -> bool:
        if not USE_NOTIFICATIONS:
            return False

        try:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

            bot = await self._get_bot()

            date_str = listing.listed_at[:10] if listing.listed_at else "—"

            # Показываем редкость атрибутов только если они есть
            attrs = []
            if listing.model:
                attrs.append(f"🏷️ <b>Модель:</b> {listing.model} ({listing.model_rarity}%)")
            if listing.backdrop:
                attrs.append(f"🖼️ <b>Фон:</b> {listing.backdrop} ({listing.backdrop_rarity}%)")
            if listing.symbol:
                attrs.append(f"🔣 <b>Символ:</b> {listing.symbol} ({listing.symbol_rarity}%)")

            attrs_str = "\n".join(attrs) if attrs else "—"

            # Разница цены к флору
            if listing.floor_price > 0:
                diff = listing.price - listing.floor_price
                diff_pct = (diff / listing.floor_price) * 100
                floor_str = f"{listing.floor_price} TON ({diff_pct:+.1f}% к флору)"
            else:
                floor_str = "—"

            text = (
                f"🎁 <b>Новый листинг!</b>\n\n"
                f"🔢 <b>Номер:</b> #{listing.tg_id}\n"
                f"📦 <b>Название:</b> {listing.name}\n"
                f"💰 <b>Цена:</b> {listing.price} TON\n"
                f"📊 <b>Флор:</b> {floor_str}\n"
                f"🕐 <b>Дата:</b> {date_str}\n\n"
                f"{attrs_str}"
            )

            if listing.photo_url:
                text += f"\n\n<a href='{listing.photo_url}'>🖼️ Фото</a>"

            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🛒 Купить",
                    url=build_portals_url(listing.gift_id),
                )
            ]])

            await bot.send_message(
                chat_id=CHAT_ID,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=False,
            )

            logger.info("📨 Уведомление отправлено в Telegram")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка отправки в Telegram: {e}")
            return False

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_listing(self, listing: Listing) -> None:
        try:
            data: list = []
            if FOUND_FILE.exists():
                with open(FOUND_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)

            data.append({
                "gift_id": listing.gift_id,
                "tg_id": listing.tg_id,
                "name": listing.name,
                "price": listing.price,
                "floor_price": listing.floor_price,
                "model": listing.model,
                "model_rarity": listing.model_rarity,
                "backdrop": listing.backdrop,
                "backdrop_rarity": listing.backdrop_rarity,
                "symbol": listing.symbol,
                "symbol_rarity": listing.symbol_rarity,
                "listed_at": listing.listed_at,
                "photo_url": listing.photo_url,
                "animation_url": listing.animation_url,
                "found_at": datetime.now().isoformat(),
            })

            with open(FOUND_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.warning(f"⚠️ Не удалось сохранить листинг: {e}")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self) -> None:
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

        logger.info("=" * 50)
        logger.info("🚀 ЗАПУСК МОНИТОРИНГА ЛИСТИНГОВ")
        logger.info("=" * 50)
        logger.info(f"⏱️  Интервал: {CHECK_INTERVAL} сек")
        logger.info(f"💰 Цена: {MIN_PRICE} – {MAX_PRICE} TON")
        logger.info(f"🔍 Фильтры: {filters_str}")
        logger.info(f"📱 Уведомления: {'ВКЛЮЧЕНЫ' if USE_NOTIFICATIONS else 'ВЫКЛЮЧЕНЫ'}")
        logger.info("=" * 50)

        if USE_NOTIFICATIONS:
            try:
                bot = await self._get_bot()
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=(
                        "🚀 <b>Мониторинг листингов запущен!</b>\n\n"
                        f"⏱️ Проверка каждые {CHECK_INTERVAL} сек\n"
                        f"💰 Диапазон цен: {MIN_PRICE} – {MAX_PRICE} TON\n"
                        f"🔍 Фильтры: {filters_str}\n\n"
                        "✅ Бот работает и ждёт новые листинги!"
                    ),
                    parse_mode="HTML",
                )
                logger.info("📨 Стартовое сообщение отправлено ✅")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки стартового сообщения: {e}")

        try:
            while True:
                try:
                    listings = await self.check_new_listings()
                    for listing in listings:
                        if USE_NOTIFICATIONS:
                            await self.send_notification(listing)
                        self._save_listing(listing)
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле мониторинга: {e}")

                await asyncio.sleep(CHECK_INTERVAL)

        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("⏹️ Остановка мониторинга...")
        finally:
            await self._close_bot()
            logger.info("👋 Завершено")


async def main() -> None:
    monitor = ListingMonitor()
    await monitor.run()


if __name__ == "__main__":
    asyncio.run(main())