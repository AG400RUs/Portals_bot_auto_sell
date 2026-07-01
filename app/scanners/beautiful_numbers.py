"""
Асинхронный охотник за красивыми номерами подарков (aportalsmp)
Использует сохранённый authData из auth.txt
Автообновление при протухании токена
"""

import os
import asyncio
import json
import logging
from typing import List, Dict, Optional, Tuple, Set, Any
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.errors import (
    AuthKeyUnregistered,
    SessionPasswordNeeded,
    PhoneNumberInvalid,
    PhoneCodeInvalid,
    PhoneCodeExpired
)
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw.functions.users import GetUsers
from pyrogram.raw.types import InputBotAppShortName, InputUser

# Импорты из aportalsmp
from aportalsmp import (
    search,
    PortalsGift,
)

# Исключения из aportalsmp
from aportalsmp.classes.Exceptions import (
    authDataError,
    requestError,
    connectionError,
    giftsError,
)

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ============= ПУТИ К ФАЙЛАМ =============

# Определяем пути относительно расположения скрипта
BASE_DIR = Path(__file__).resolve().parent.parent  # app/
TOOLS_DIR = BASE_DIR / "tools"  # app/tools/
AUTH_FILE = TOOLS_DIR / "auth.txt"

logger.info(f"📂 AUTH_FILE: {AUTH_FILE}")


# ============= ФУНКЦИЯ ЗАГРУЗКИ AUTH ИЗ ФАЙЛА =============

def load_cached_auth() -> Optional[str]:
    """
    Загружает authData из файла auth.txt.
    """
    if AUTH_FILE.exists():
        auth_data = AUTH_FILE.read_text(encoding="utf-8").strip()
        if auth_data:
            logger.info(f"📂 Загружен authData из {AUTH_FILE} ({len(auth_data)} символов)")
            return auth_data
    return None


# ============= ФУНКЦИЯ ПОЛУЧЕНИЯ AUTHData ЧЕРЕЗ СЕССИЮ =============

async def get_auth_data() -> str:
    """
    Получает authData через pyrogram и сохраняет в auth.txt.
    """
    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    session_name = os.getenv("SESSION_NAME", "portals_account")

    if not api_id:
        raise RuntimeError("Missing env var: API_ID")
    if not api_hash:
        raise RuntimeError("Missing env var: API_HASH")

    session_path = TOOLS_DIR / f"{session_name}.session"

    if not session_path.exists():
        raise FileNotFoundError(
            f"❌ Файл сессии не найден: {session_path}\n"
            f"   Сначала создай сессию через get_auth_pyrofork.py"
        )

    logger.info(f"📂 Использую существующую сессию: {session_path}")

    client = Client(
        name=session_name,
        api_id=int(api_id),
        api_hash=api_hash,
        workdir=str(TOOLS_DIR),
        in_memory=False,
        # qr_login убран
    )

    try:
        await client.start()

        me = await client.get_me()
        logger.info(f"✅ Сессия активна! Пользователь: {me.first_name} (@{me.username})")

        peer = await client.resolve_peer("portals")

        bot_raw = (await client.invoke(GetUsers(id=[peer])))[0]
        bot = InputUser(
            user_id=bot_raw.id,
            access_hash=bot_raw.access_hash,
        )

        web_view = await client.invoke(
            RequestAppWebView(
                peer=peer,
                app=InputBotAppShortName(
                    bot_id=bot,
                    short_name="market",
                ),
                platform="desktop",
            )
        )

        init_data = unquote(
            web_view.url
            .split("tgWebAppData=", 1)[1]
            .split("&tgWebAppVersion", 1)[0]
        )

        auth_data = f"tma {init_data}"

        AUTH_FILE.write_text(auth_data, encoding="utf-8")
        logger.info(f"✅ authData сохранён в {AUTH_FILE}")
        logger.info(f"📏 Длина: {len(auth_data)} символов")

        return auth_data

    except (AuthKeyUnregistered, PhoneNumberInvalid) as e:
        logger.error(f"❌ Ошибка сессии: {e}")
        raise FileNotFoundError(
            f"❌ Сессия {session_name} недействительна. Создай новую через get_auth_pyrofork.py"
        )
    except SessionPasswordNeeded:
        logger.error("❌ Требуется пароль двухфакторной аутентификации")
        raise
    except (PhoneCodeInvalid, PhoneCodeExpired) as e:
        logger.error(f"❌ Неверный код подтверждения: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Неизвестная ошибка: {e}")
        raise
    finally:
        await client.stop()
        logger.debug("🔒 Сессия закрыта")

# ============= ВСПОМОГАТЕЛЬНЫЙ КЛАСС ДЛЯ ФИЛЬТРОВ =============

class SearchFilters:
    """Класс для удобной работы с фильтрами поиска"""

    def __init__(
        self,
        min_price: float = 0,
        max_price: float = 100000,
        sort: str = "price_asc",
        gift_name: Optional[str] = None,
        model: Optional[str] = None,
        backdrop: Optional[str] = None,
        symbol: Optional[str] = None
    ):
        self.min_price = min_price
        self.max_price = max_price
        self.sort = sort
        self.gift_name = gift_name
        self.model = model
        self.backdrop = backdrop
        self.symbol = symbol

    def to_dict(self) -> Dict[str, Any]:
        """Преобразует фильтры в словарь для передачи в API"""
        result = {
            "min_price": self.min_price,
            "max_price": self.max_price,
            "sort": self.sort
        }

        if self.gift_name:
            result["gift_name"] = self.gift_name
        if self.model:
            result["model"] = self.model
        if self.backdrop:
            result["backdrop"] = self.backdrop
        if self.symbol:
            result["symbol"] = self.symbol

        return result


# ============= КЛАССЫ ДЛЯ ДАННЫХ =============

@dataclass
class BeautifulGift:
    """Класс для хранения информации о найденном подарке с красивым номером"""
    id: str
    number: int
    name: str
    price: float
    beauty_type: str
    photo_url: str = ""
    model: str = ""
    symbol: str = ""
    backdrop: str = ""
    rarity: float = 0.0
    floor_price: float = 0.0
    listed_at: str = ""

    def __str__(self) -> str:
        return f"#{self.number} [{self.beauty_type}] {self.name} — {self.price} USDT"


# ============= ОСНОВНОЙ КЛАСС ОХОТНИКА =============

class BeautifulGiftHunter:
    """
    Асинхронный охотник за красивыми номерами подарков.
    Использует сохранённый authData из auth.txt.
    """

    def __init__(
        self,
        auth_data: Optional[str] = None,
        auto_refresh: bool = True,
        use_cache: bool = True
    ):
        self._auth_data = auth_data
        self.auto_refresh = auto_refresh
        self.use_cache = use_cache
        self._auth_refresh_time: Optional[datetime] = None
        self._total_checked = 0
        self._found_count = 0

        if use_cache and self._auth_data is None:
            cached = load_cached_auth()
            if cached:
                self._auth_data = cached
                self._auth_refresh_time = datetime.now()

    @property
    async def auth_data(self) -> str:
        """Получает актуальный authData с автоматическим обновлением"""
        if self._auth_data is None or self._needs_refresh():
            await self.refresh_auth()
        return self._auth_data

    async def refresh_auth(self) -> None:
        """Обновляет authData через существующую сессию"""
        try:
            logger.info("🔄 Обновляю authData через существующую сессию...")
            self._auth_data = await get_auth_data()
            self._auth_refresh_time = datetime.now()
            logger.info("✅ authData успешно обновлен")
        except Exception as e:
            logger.error(f"❌ Ошибка обновления authData: {e}")
            raise

    def _needs_refresh(self) -> bool:
        """Проверяет, нужно ли обновить authData (каждые 30 минут)"""
        if self._auth_refresh_time is None:
            return True
        delta = datetime.now() - self._auth_refresh_time
        return delta.total_seconds() > 1800

    # ============= СТАТИЧЕСКИЕ МЕТОДЫ ДЛЯ ПРОВЕРКИ ЧИСЕЛ =============

    @staticmethod
    def is_repeating_number(num: int) -> bool:
        """Проверка на повторяющиеся цифры (111, 222, 3333...)"""
        return len(set(str(num))) == 1

    @staticmethod
    def is_palindrome(num: int) -> bool:
        """Проверка на палиндром (1001, 202, 12321...)"""
        num_str = str(num)
        return num_str == num_str[::-1]

    @staticmethod
    def is_beautiful_number(num: int) -> Tuple[bool, str]:
        """
        Комплексная проверка числа.

        Returns:
            Tuple[bool, str]: (является красивым, тип красоты)
        """
        if BeautifulGiftHunter.is_repeating_number(num):
            return True, "Повтор"
        elif BeautifulGiftHunter.is_palindrome(num):
            return True, "Палиндром"
        return False, ""

    # ============= ОСНОВНЫЕ МЕТОДЫ ПОИСКА =============

    async def search_beautiful_gifts(
            self,
            min_price: float = 0,
            max_price: float = 1000,
            max_results: int = 50,
            sort: str = "price_asc",
            gift_name: Optional[str] = None,
            model: Optional[str] = None,
            backdrop: Optional[str] = None,
            symbol: Optional[str] = None,
            include_types: Optional[List[str]] = None
    ) -> List[BeautifulGift]:
        self._total_checked = 0
        self._found_count = 0
        beautiful_gifts = []

        filters = SearchFilters(
            min_price=min_price,
            max_price=max_price,
            sort=sort,
            gift_name=gift_name,
            model=model,
            backdrop=backdrop,
            symbol=symbol
        )

        offset = 0
        limit = 20
        page = 0

        logger.info(f"🔍 Поиск красивых номеров (цена: {min_price}-{max_price} USDT)")

        while len(beautiful_gifts) < max_results:
            try:
                auth = await self.auth_data

                batch = await search(
                    authData=auth,
                    offset=offset,
                    limit=limit,
                    **filters.to_dict()
                )

                if not batch:
                    logger.debug(f"📭 Подарков больше нет (проверено {offset} записей)")
                    break

                page += 1
                logger.info(f"📦 Страница {page}: проверяем {len(batch)} подарков")

                for gift in batch:  # ← напрямую работаем с объектом PortalsGift
                    self._total_checked += 1

                    try:
                        # Проверяем наличие номера
                        if not hasattr(gift, 'external_collection_number'):
                            continue

                        number = gift.external_collection_number
                        if number is None:
                            continue

                        is_beautiful, beauty_type = self.is_beautiful_number(number)

                        if is_beautiful and include_types and beauty_type not in include_types:
                            continue

                        if is_beautiful:
                            beautiful_gift = self._convert_to_beautiful_gift(gift, beauty_type)
                            beautiful_gifts.append(beautiful_gift)
                            self._found_count += 1
                            logger.info(f"✨ Найден {beauty_type}: #{number} ({gift.name}) — {gift.price} USDT")

                            if len(beautiful_gifts) >= max_results:
                                break

                    except Exception as e:
                        logger.error(f"❌ Ошибка обработки подарка: {e}")
                        continue

                if len(batch) < limit:
                    logger.info(f"📭 Это была последняя страница")
                    break

                await asyncio.sleep(1)
                offset += limit

            except authDataError as e:
                if self.auto_refresh:
                    logger.warning(f"⚠️ Ошибка авторизации, обновляю токен: {e}")
                    await self.refresh_auth()
                    continue
                else:
                    logger.error(f"❌ Критическая ошибка авторизации: {e}")
                    break
            except (requestError, connectionError) as e:
                if "429" in str(e) or "too many requests" in str(e).lower():
                    logger.warning(f"⚠️ Превышен лимит запросов, жду 5 секунд...")
                    await asyncio.sleep(5)
                    continue
                else:
                    logger.error(f"❌ Ошибка запроса/соединения: {e}")
                    await asyncio.sleep(2)
                    continue
            except giftsError as e:
                logger.error(f"❌ Ошибка при работе с подарками: {e}")
                break
            except Exception as e:
                logger.error(f"❌ Непредвиденная ошибка: {e}")
                logger.error(f"   Тип ошибки: {type(e).__name__}")
                break

        logger.info(f"✅ Завершено: проверено {self._total_checked} подарков, найдено {self._found_count}")
        return beautiful_gifts[:max_results]
    async def search_specific_numbers(
        self,
        target_numbers: List[int],
        min_price: float = 0,
        max_price: float = 1000,
        max_results: int = 100
    ) -> List[BeautifulGift]:
        """
        Ищет подарки с конкретными номерами из списка.
        """
        target_set = set(target_numbers)
        found_gifts = []
        remaining = target_set.copy()

        offset = 0
        limit = 20

        logger.info(f"🔍 Ищу конкретные номера: {', '.join(map(str, sorted(target_numbers)[:10]))}...")

        while len(found_gifts) < max_results and remaining:
            try:
                auth = await self.auth_data

                batch = await search(
                    authData=auth,
                    min_price=min_price,
                    max_price=max_price,
                    offset=offset,
                    limit=limit,
                    sort="price_asc"
                )

                if not batch:
                    break

                for raw_gift in batch:
                    try:
                        if isinstance(raw_gift, dict):
                            gift = PortalsGift(raw_gift)
                        else:
                            gift = raw_gift

                        number = gift.external_collection_number if hasattr(gift, 'external_collection_number') else None

                        if number in remaining:
                            found_gift = self._convert_to_beautiful_gift(gift, "По списку")
                            found_gifts.append(found_gift)
                            remaining.remove(number)
                            logger.info(f"✅ Найден номер {number} ({gift.name})")

                            if not remaining:
                                break
                    except Exception as e:
                        logger.error(f"❌ Ошибка обработки подарка: {e}")
                        continue

                if len(batch) < limit:
                    break

                await asyncio.sleep(0.5)
                offset += limit

            except (requestError, connectionError) as e:
                logger.error(f"❌ Ошибка соединения: {e}")
                await asyncio.sleep(2)
                continue
            except Exception as e:
                logger.error(f"❌ Ошибка: {e}")
                break

        if remaining:
            logger.warning(f"⚠️ Не найдены номера: {', '.join(map(str, sorted(remaining)))}")

        return found_gifts

    # ============= ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =============

    def _convert_to_beautiful_gift(self, gift: PortalsGift, beauty_type: str) -> BeautifulGift:
        """Конвертирует объект PortalsGift в BeautifulGift"""
        return BeautifulGift(
            id=gift.id,
            number=gift.external_collection_number,
            name=gift.name or "Без названия",
            price=float(gift.price) if gift.price else 0.0,
            beauty_type=beauty_type,
            photo_url=gift.photo_url or "",
            model=gift.model or "",
            symbol=gift.symbol or "",
            backdrop=gift.backdrop or "",
            rarity=gift.model_rarity or 0.0,
            floor_price=float(gift.floor_price) if gift.floor_price else 0.0,
            listed_at=gift.listed_at or "",
        )


# ============= УТИЛИТЫ ДЛЯ ВЫВОДА =============

def format_gifts_table(gifts: List[BeautifulGift], limit: int = 20) -> str:
    """Форматирует список подарков в виде таблицы"""
    if not gifts:
        return "😔 Красивых номеров не найдено"

    sorted_gifts = sorted(gifts, key=lambda x: x.number)
    display_gifts = sorted_gifts[:limit]

    lines = [
        "=" * 70,
        f"🎁 НАЙДЕНО {len(sorted_gifts)} ПОДАРКОВ С КРАСИВЫМИ НОМЕРАМИ",
        "=" * 70
    ]

    for i, gift in enumerate(display_gifts, 1):
        lines.extend([
            "",
            f"{i}. #{gift.number} [{gift.beauty_type}]",
            f"   📦 {gift.name}",
            f"   💰 {gift.price} USDT",
            f"   🏷️  Модель: {gift.model or '—'}, Символ: {gift.symbol or '—'}",
            f"   🔗 ID: {gift.id[:12]}..."
        ])

    if len(sorted_gifts) > limit:
        lines.append(f"\n... и еще {len(sorted_gifts) - limit} подарков")

    lines.append("-" * 70)
    return "\n".join(lines)


def save_results(gifts: List[BeautifulGift], filename: str = "beautiful_gifts.json"):
    """Сохраняет результаты в JSON-файл"""
    if not gifts:
        return

    data = []
    for gift in gifts:
        data.append({
            "number": gift.number,
            "name": gift.name,
            "price": gift.price,
            "beauty_type": gift.beauty_type,
            "id": gift.id,
            "model": gift.model,
            "symbol": gift.symbol,
            "backdrop": gift.backdrop,
            "photo_url": gift.photo_url,
            "floor_price": gift.floor_price,
            "listed_at": gift.listed_at
        })

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(f"💾 Результаты сохранены в {filename}")


# ============= ОСНОВНАЯ ФУНКЦИЯ =============

async def main():
    """
    Основная функция для демонстрации работы.
    """
    logger.info("=" * 50)
    logger.info("ЗАПУСК ОХОТНИКА ЗА КРАСИВЫМИ НОМЕРАМИ")
    logger.info("=" * 50)

    try:
        # 1. Пробуем загрузить authData из auth.txt
        auth_data = load_cached_auth()

        # 2. Если нет — получаем через сессию
        if auth_data is None:
            logger.info("🔄 auth.txt не найден, получаем authData через pyrogram...")
            auth_data = await get_auth_data()
        else:
            logger.info("✅ Использую сохранённый authData из auth.txt")

        # 3. Создаём охотника
        hunter = BeautifulGiftHunter(
            auth_data=auth_data,
            auto_refresh=True,
            use_cache=True
        )

        # ===== ВАРИАНТ 1: Поиск всех красивых номеров =====
        logger.info("\n" + "=" * 50)
        logger.info("ВАРИАНТ 1: Поиск красивых номеров (цена 50-300 GRAM)")

        beautiful_gifts = await hunter.search_beautiful_gifts(
            min_price=50,
            max_price=300,
            max_results=20,
            sort="price_asc"
        )
        print(format_gifts_table(beautiful_gifts))

        if beautiful_gifts:
            save_results(beautiful_gifts)

        # ===== ВАРИАНТ 2: Поиск конкретных номеров =====
        logger.info("\n" + "=" * 50)
        logger.info("ВАРИАНТ 2: Поиск конкретных номеров")

        specific_numbers = [111, 222, 333, 444, 555, 1001, 2002, 101, 202, 303, 404, 505, 606, 707, 666, 777, 888, 999]
        specific_gifts = await hunter.search_specific_numbers(
            target_numbers=specific_numbers,
            min_price=50,
            max_price=300
        )
        print(format_gifts_table(specific_gifts))

        # ===== ВАРИАНТ 3: Только палиндромы =====
        logger.info("\n" + "=" * 50)
        logger.info("ВАРИАНТ 3: Только палиндромы (цена 0-3 USDT)")

        palindromes = await hunter.search_beautiful_gifts(
            min_price=50,
            max_price=300,
            max_results=10,
            include_types=["Палиндром"]
        )
        print(format_gifts_table(palindromes))

    except FileNotFoundError as e:
        logger.error(f"\n❌ {e}")
        logger.info("📌 Сначала запусти get_auth_pyrofork.py для создания сессии")
    except Exception as e:
        logger.error(f"\n❌ Критическая ошибка: {e}")


if __name__ == "__main__":
    asyncio.run(main())