import asyncio
import os
from pathlib import Path
from urllib.parse import unquote

from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw.functions.users import GetUsers
from pyrogram.raw.types import InputBotAppShortName, InputUser

load_dotenv()


async def get_auth_data():
    api_id = int(os.getenv("API_ID"))
    api_hash = os.getenv("API_HASH")
    session_name = os.getenv("SESSION_NAME", "portals_account")

    async with Client(
        session_name,
        api_id=api_id,
        api_hash=api_hash,
        workdir=os.getcwd(),
    ) as client:
        peer = await client.resolve_peer("portals")

        user_full = await client.invoke(GetUsers(id=[peer]))
        bot_raw = user_full[0]

        bot = InputUser(
            user_id=bot_raw.id,
            access_hash=bot_raw.access_hash,
        )

        bot_app = InputBotAppShortName(
            bot_id=bot,
            short_name="market",
        )

        web_view = await client.invoke(
            RequestAppWebView(
                peer=peer,
                app=bot_app,
                platform="desktop",
            )
        )

        init_data = unquote(
            web_view.url
            .split("tgWebAppData=", 1)[1]
            .split("&tgWebAppVersion", 1)[0]
        )

        return f"tma {init_data}"


async def main():
    auth_data = await get_auth_data()

    auth_path = Path("auth.txt")
    auth_path.write_text(auth_data, encoding="utf-8")

    print("AUTH_DATA сохранён в:", auth_path.resolve())
    print("Длина AUTH_DATA:", len(auth_data))


if __name__ == "__main__":
    asyncio.run(main())