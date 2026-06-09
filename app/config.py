import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        self.BOT_TOKEN = self._req("BOT_TOKEN")
        self.AUTH_DATA = self._req("AUTH_DATA")

        self.ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

        self.TARGET_NFT_ID = self._req("TARGET_NFT_ID")

        self.BASE_PRICE = float(os.getenv("BASE_PRICE", 2.6))
        self.DELTA = float(os.getenv("DELTA", 0.01))
        self.INTERVAL = int(os.getenv("INTERVAL", 30))

    def _req(self, key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise RuntimeError(f"Missing required env var: {key}")
        return value