import asyncio
import traceback
from datetime import datetime

from app.tools.constants import AUTH_FILE
from app.tools.get_auth_pyrofork import get_auth_data

REFRESH_INTERVAL = 60 * 60 * 3  # 3 часа


async def refresh_auth():
    print(f"[AUTH] Начинаю обновление: {datetime.now()}")

    auth_data = await get_auth_data()

    if not auth_data:
        raise RuntimeError("get_auth_data вернул пустой AUTH_DATA")

    AUTH_FILE.write_text(
        auth_data,
        encoding="utf-8"
    )

    print(f"[AUTH] Обновлён успешно")
    print(f"[AUTH] Файл: {AUTH_FILE}")
    print(f"[AUTH] Длина: {len(auth_data)}")
    print(f"[AUTH] Время: {datetime.now()}")


async def main():
    print("[AUTH] auth_refresher запущен")

    while True:
        try:
            await refresh_auth()

        except Exception:
            print("[AUTH] Ошибка обновления AUTH_DATA")
            traceback.print_exc()

        print(f"[AUTH] Следующее обновление через 3 часа")
        await asyncio.sleep(REFRESH_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())