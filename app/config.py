import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        self.BOT_TOKEN = self._req("BOT_TOKEN")
        self.AUTH_DATA = os.getenv("AUTH_DATA", "")

        self.ADMIN_ID = int(self._req("ADMIN_ID"))

        # self.API_ID = int(self._req("API_ID"))
        # self.API_HASH = self._req("API_HASH")
        # self.SESSION_NAME = os.getenv("SESSION_NAME", "portals_account")
        # self.SESSION_PATH = os.getenv("SESSION_PATH", ".")

    def _req(self, key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise RuntimeError(f"Missing required env var: {key}")
        return value