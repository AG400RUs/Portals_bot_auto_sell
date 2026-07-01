"""
Мониторинг новых листингов с красивыми номерами на Portals Market
Отправляет уведомления в Telegram при обнаружении
"""

import os
import asyncio
import json
import logging
from typing import List, Optional, Tuple
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from urllib.parse import unquote

from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw.functions.users import GetUsers
from pyrogram.raw.types import InputBotAppShortName, InputUser

from aportalsmp import marketActivity, PortalsGift
from aportalsmp.classes.Exceptions import authDataError, requestError, connectionError

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
STATE_FILE = TOOLS_DIR / "last_activity_id.txt"
FOUND_FILE = TOOLS_DIR / "found_beautiful_listings.json"
TARGET_FILE = TOOLS_DIR / "target_numbers.txt"

# ===== НАСТРОЙКИ ПОИСКА =====
CHECK_INTERVAL = 30
MIN_PRICE = 0
MAX_PRICE = 100000
# Максимум листингов за один запрос. Если за CHECK_INTERVAL выходит больше —
# увеличь это значение, чтобы не пропускать листинги.
FETCH_LIMIT = 50

# ===== НАСТРОЙКИ ТЕЛЕГРАМ-БОТА =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("ADMIN_ID", "")
USE_NOTIFICATIONS = bool(BOT_TOKEN and CHAT_ID)


# ===== ЗАГРУЗКА ЦЕЛЕВЫХ НОМЕРОВ ИЗ ФАЙЛА =====

def load_target_numbers() -> List[int]:
    """
    Загружает список целевых номеров из файла tools/target_numbers.txt.
    Если файл не найден — создаёт пример и возвращает пустой список
    (режим «все красивые номера»).
    """
    numbers = []

    if not TARGET_FILE.exists():
        logger.warning(f"⚠️ Файл {TARGET_FILE} не найден, создаю пример...")
        example_content = """# Целевые номера для мониторинга
# Каждый номер с новой строки
# Пустые строки и строки с # игнорируются
# Если файл пустой (только комментарии) — отслеживаются ВСЕ красивые номера

# Повторы
111
222
333

# Палиндромы
1001
2002
3003
"""
        TARGET_FILE.write_text(example_content, encoding="utf-8")
        logger.info(f"✅ Создан пример файла: {TARGET_FILE}")
        logger.info("ℹ️  Фильтр по номерам ВЫКЛЮЧЕН — отслеживаются все красивые номера")
        return numbers

    try:
        with open(TARGET_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                try:
                    numbers.append(int(line))
                except ValueError:
                    logger.warning(f"⚠️ Пропускаю некорректный номер: {line!r}")

        if numbers:
            logger.info(f"📂 Загружено {len(numbers)} целевых номеров из {TARGET_FILE}")
        else:
            logger.info("ℹ️  target_numbers.txt пустой — отслеживаются все красивые номера")

        return numbers

    except Exception as e:
        logger.error(f"❌ Ошибка загрузки target_numbers.txt: {e}")
        return []


@dataclass
class BeautifulListing:
    activity_id: str
    gift_id: str
    number: int
    name: str
    price: float
    beauty_type: str
    listed_at: str
    photo_url: str = ""
    model: str = ""
    symbol: str = ""


class BeautifulListingMonitor:
    def __init__(self, target_numbers: List[int]):
        self._target_numbers = target_numbers
        self._last_activity_id = self._load_state()
        self._bot = None

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> Optional[str]:
        if STATE_FILE.exists():
            try:
                data = STATE_FILE.read_text(encoding="utf-8").strip()
                if data:
                    logger.info(f"📂 Загружен последний activity_id: {data}")
                    return data
            except Exception as e:
                logger.warning(f"⚠️ Не удалось загрузить state: {e}")
        return None

    def _save_state(self, activity_id: str) -> None:
        try:
            STATE_FILE.write_text(activity_id, encoding="utf-8")
            logger.debug(f"💾 Сохранён activity_id: {activity_id}")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось сохранить state: {e}")

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _get_auth_data(self) -> str:
        if AUTH_FILE.exists():
            auth_data = AUTH_FILE.read_text(encoding="utf-8").strip()
            if auth_data:
                logger.info(f"📂 Загружен authData из кэша ({len(auth_data)} символов)")
                return auth_data

        logger.info("🔄 Получаю новый authData...")

        api_id = os.getenv("API_ID")
        api_hash = os.getenv("API_HASH")
        session_name = os.getenv("SESSION_NAME", "portals_account")

        if not api_id or not api_hash:
            raise RuntimeError("Missing API_ID or API_HASH in .env")

        session_path = TOOLS_DIR / f"{session_name}.session"
        if not session_path.exists():
            raise FileNotFoundError(f"❌ Сессия не найдена: {session_path}")

        client = Client(
            name=session_name,
            api_id=int(api_id),
            api_hash=api_hash,
            workdir=str(TOOLS_DIR),
            in_memory=False,
        )

        try:
            await client.start()

            peer = await client.resolve_peer("portals")
            bot_raw = (await client.invoke(GetUsers(id=[peer])))[0]
            bot = InputUser(
                user_id=bot_raw.id,
                access_hash=bot_raw.access_hash,
            )

            web_view = await client.invoke(
                RequestAppWebView(
                    peer=peer,
                    app=InputBotAppShortName(bot_id=bot, short_name="market"),
                    platform="desktop",
                )
            )

            init_data = (
                web_view.url
                .split("tgWebAppData=", 1)[1]
                .split("&tgWebAppVersion", 1)[0]
            )
            auth_data = f"tma {unquote(init_data)}"

            AUTH_FILE.write_text(auth_data, encoding="utf-8")
            logger.info(f"✅ authData сохранён в {AUTH_FILE}")
            return auth_data

        finally:
            await client.stop()

    # ------------------------------------------------------------------
    # Beauty check
    # ------------------------------------------------------------------

    @staticmethod
    def is_beautiful_number(num: int) -> Tuple[bool, str]:
        num_str = str(num)
        if len(set(num_str)) == 1:
            return True, "Повтор"
        if num_str == num_str[::-1]:
            return True, "Палиндром"
        return False, ""

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    async def check_new_listings(self) -> List[BeautifulListing]:
        try:
            auth = await self._get_auth_data()

            activities = await marketActivity(
                authData=auth,
                sort="latest",
                offset=0,
                limit=FETCH_LIMIT,
                min_price=MIN_PRICE,
                max_price=MAX_PRICE,
                activityType="listing",
            )

            if not activities:
                return []

            # Собираем только новые активности (до last_activity_id)
            new_activities = []
            first_new_id: Optional[str] = None

            for activity in activities:
                activity_id = getattr(activity, 'id', None)

                if activity_id == self._last_activity_id:
                    break

                if getattr(activity, 'type', '') != 'listing':
                    continue

                new_activities.append((activity_id, activity))

                if first_new_id is None:
                    first_new_id = activity_id

            if not new_activities:
                return []

            logger.info(f"📦 Найдено {len(new_activities)} новых листингов")

            beautiful_listings = []

            for activity_id, activity in new_activities:
                try:
                    gift_data = getattr(activity, 'nft', None)
                    if not gift_data:
                        continue

                    gift = PortalsGift(gift_data) if isinstance(gift_data, dict) else gift_data

                    number = getattr(gift, 'external_collection_number', None)
                    if number is None:
                        continue

                    # Фильтр по конкретным номерам (если список задан)
                    if self._target_numbers and number not in self._target_numbers:
                        continue

                    is_beautiful, beauty_type = self.is_beautiful_number(number)
                    if not is_beautiful:
                        continue

                    raw_price = getattr(gift, 'price', 0)
                    try:
                        price = float(raw_price) if raw_price else 0.0
                    except (TypeError, ValueError):
                        price = 0.0

                    listing = BeautifulListing(
                        activity_id=activity_id,
                        gift_id=getattr(gift, 'id', ''),
                        number=number,
                        name=getattr(gift, 'name', 'Без названия'),
                        price=price,
                        beauty_type=beauty_type,
                        listed_at=getattr(gift, 'listed_at', ''),
                        photo_url=getattr(gift, 'photo_url', ''),
                        model=getattr(gift, 'model', ''),
                        symbol=getattr(gift, 'symbol', ''),
                    )
                    beautiful_listings.append(listing)
                    logger.info(
                        f"✨ Найден {beauty_type}: #{number} ({listing.name}) — {price} USDT"
                    )

                except Exception as e:
                    logger.error(f"❌ Ошибка обработки активности {activity_id}: {e}")
                    continue

            # Обновляем курсор только после успешной обработки всего батча
            if first_new_id:
                self._last_activity_id = first_new_id
                self._save_state(first_new_id)

            return beautiful_listings

        except authDataError as e:
            logger.error(f"❌ Ошибка авторизации: {e}")
            AUTH_FILE.unlink(missing_ok=True)
            return []
        except (requestError, connectionError) as e:
            logger.error(f"❌ Ошибка соединения: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Непредвиденная ошибка: {e}")
            return []

    # ------------------------------------------------------------------
    # Telegram
    # ------------------------------------------------------------------

    async def _get_bot(self):
        """Ленивая инициализация бота."""
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

    async def send_telegram_notification(self, listing: BeautifulListing) -> bool:
        if not USE_NOTIFICATIONS:
            return False

        try:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

            bot = await self._get_bot()

            emoji = "🔁" if listing.beauty_type == "Повтор" else "🔄"
            date_str = listing.listed_at[:10] if listing.listed_at else "—"

            text = (
                f"🎯 <b>Найден красивый номер!</b>\n\n"
                f"{emoji} <b>Тип:</b> {listing.beauty_type}\n"
                f"🔢 <b>Номер:</b> #{listing.number}\n"
                f"📦 <b>Название:</b> {listing.name}\n"
                f"💰 <b>Цена:</b> {listing.price} USDT\n"
                f"🏷️ <b>Модель:</b> {listing.model or '—'}\n"
                f"🔣 <b>Символ:</b> {listing.symbol or '—'}\n"
                f"🕐 <b>Опубликован:</b> {date_str}\n"
                f"\n<a href='{listing.photo_url}'>🖼️ Фото</a>"
            )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🛒 Купить",
                    url=f"https://portals-market.com/gift/{listing.gift_id}",
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

    def _save_listing(self, listing: BeautifulListing) -> None:
        try:
            data: list = []
            if FOUND_FILE.exists():
                with open(FOUND_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)

            data.append({
                "activity_id": listing.activity_id,
                "gift_id": listing.gift_id,
                "number": listing.number,
                "name": listing.name,
                "price": listing.price,
                "beauty_type": listing.beauty_type,
                "listed_at": listing.listed_at,
                "photo_url": listing.photo_url,
                "model": listing.model,
                "symbol": listing.symbol,
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
        logger.info("=" * 50)
        logger.info("🚀 ЗАПУСК МОНИТОРИНГА НОВЫХ ЛИСТИНГОВ")
        logger.info("=" * 50)
        logger.info(f"⏱️ Интервал проверки: {CHECK_INTERVAL} сек")
        logger.info(f"💰 Диапазон цен: {MIN_PRICE} – {MAX_PRICE} USDT")
        logger.info(f"🎯 Фильтр по номерам: {self._target_numbers or 'все красивые'}")
        logger.info(f"📱 Уведомления: {'ВКЛЮЧЕНЫ' if USE_NOTIFICATIONS else 'ВЫКЛЮЧЕНЫ'}")
        logger.info("=" * 50)

        # Тестовое уведомление при старте
        if USE_NOTIFICATIONS:
            try:
                bot = await self._get_bot()
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=(
                        "🚀 <b>Мониторинг запущен!</b>\n\n"
                        f"⏱️ Проверка каждые {CHECK_INTERVAL} сек\n"
                        f"💰 Диапазон цен: {MIN_PRICE} – {MAX_PRICE} USDT\n"
                        f"🎯 Типы: повторы и палиндромы\n\n"
                        "✅ Бот работает и ждёт новые листинги!"
                    ),
                    parse_mode="HTML",
                )
                logger.info("📨 Тестовое сообщение отправлено в Telegram ✅")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки тестового сообщения: {e}")
                logger.error("   Проверь BOT_TOKEN и ADMIN_ID в .env")

        # Основной цикл
        try:
            while True:
                try:
                    listings = await self.check_new_listings()
                    for listing in listings:
                        if USE_NOTIFICATIONS:
                            await self.send_telegram_notification(listing)
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
    target_numbers = load_target_numbers()
    monitor = BeautifulListingMonitor(target_numbers=target_numbers)
    await monitor.run()


if __name__ == "__main__":
    asyncio.run(main())