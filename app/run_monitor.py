import asyncio

from app.tools.get_auth_pyrofork import get_auth_data
from app.tools.constants import AUTH_FILE
from app.tools.auth_refresher import main as auth_refresher_main
from app.scanners.collection_monitor import main as monitor_main


async def prepare_auth():
    print("Получаю первичный AUTH_DATA...")

    auth_data = await get_auth_data()

    AUTH_FILE.write_text(
        auth_data,
        encoding="utf-8"
    )

    print("Первичный AUTH_DATA сохранён")


async def main():
    await prepare_auth()

    await asyncio.gather(
        auth_refresher_main(),
        monitor_main(),
    )


if __name__ == "__main__":
    asyncio.run(main())