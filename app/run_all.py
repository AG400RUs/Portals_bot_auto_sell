import asyncio

from app.main import main as bot_main
from app.scanners.collection_monitor import main as monitor_main
from app.tools.auth_refresher import main as auth_refresher_main


async def main():
    await asyncio.gather(
        bot_main(),
        monitor_main(),
        auth_refresher_main(),
    )


if __name__ == "__main__":
    asyncio.run(main())