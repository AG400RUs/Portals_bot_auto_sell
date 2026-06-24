import os
from pathlib import Path
from urllib.parse import unquote

from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw.functions.users import GetUsers
from pyrogram.raw.types import InputBotAppShortName, InputUser

load_dotenv()

TOOLS_DIR = Path(__file__).resolve().parent


async def get_auth_data() -> str:
    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    session_name = os.getenv("SESSION_NAME", "portals_account")

    if not api_id:
        raise RuntimeError("Missing env var: API_ID")

    if not api_hash:
        raise RuntimeError("Missing env var: API_HASH")

    async with Client(
        name=session_name,
        api_id=int(api_id),
        api_hash=api_hash,
        workdir=str(TOOLS_DIR),
    ) as client:
        peer = await client.resolve_peer("portals")

        bot_raw = (
            await client.invoke(
                GetUsers(id=[peer])
            )
        )[0]

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

        return f"tma {init_data}"


async def main():
    from app.tools.constants import AUTH_FILE

    auth_data = await get_auth_data()

    AUTH_FILE.write_text(
        auth_data,
        encoding="utf-8"
    )

    print("AUTH_DATA сохранён в:", AUTH_FILE)
    print("Длина AUTH_DATA:", len(auth_data))


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())