import asyncio
from pathlib import Path


from app.tools.get_auth_pyrofork import get_auth_data


AUTH_FILE = Path("auth.txt")
REFRESH_INTERVAL = 60 * 60 * 3  # 3 часа


async def main():
    while True:
        try:
            auth_data = await get_auth_data()

            AUTH_FILE.write_text(
                auth_data,
                encoding="utf-8"
            )

            print("AUTH_DATA обновлён в auth.txt")

        except Exception as e:
            print("Ошибка обновления AUTH_DATA:", e)

        await asyncio.sleep(REFRESH_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())