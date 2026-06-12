import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        self.BOT_TOKEN = self._req("BOT_TOKEN")
        self.AUTH_DATA = self._req("AUTH_DATA")

    def _req(self, key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise RuntimeError(f"Missing required env var: {key}")
        return value