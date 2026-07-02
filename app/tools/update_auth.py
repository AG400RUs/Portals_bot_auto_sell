import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from pyrogram import Client

load_dotenv()

TOOLS_DIR = Path(__file__).resolve().parent
SESSION_NAME = "portals_account"


async def main():
    api_id = int(os.getenv("API_ID"))
    api_hash = os.getenv("API_HASH")

    async with Client(
        name=SESSION_NAME,
        api_id=api_id,
        api_hash=api_hash,
        workdir=str(TOOLS_DIR),
    ):
        print("✅ Сессия успешно создана")
        print("Файл:", TOOLS_DIR / f"{SESSION_NAME}.session")


if __name__ == "__main__":
    asyncio.run(main())