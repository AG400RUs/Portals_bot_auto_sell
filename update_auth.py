import asyncio
import os

from dotenv import load_dotenv
from aportalsmp.auth import update_auth

load_dotenv()


async def main():
    api_id = int(os.getenv("API_ID"))
    api_hash = os.getenv("API_HASH")

    auth_data = await update_auth(
        api_id=api_id,
        api_hash=api_hash,
        session_name="portals_account",
    )

    print("\nNEW AUTH_DATA:\n")
    print(auth_data)


if __name__ == "__main__":
    asyncio.run(main())