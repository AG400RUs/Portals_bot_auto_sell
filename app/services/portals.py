from aportalsmp import myPortalsGifts, changePrice, marketActivity, collections
from app.tools.constants import AUTH_FILE


class PortalsService:
    def __init__(self, config):
        self.config = config

    def get_auth_data(self):
        if not AUTH_FILE.exists():
            raise RuntimeError(
                f"AUTH файл не найден: {AUTH_FILE}"
            )

        return AUTH_FILE.read_text(
            encoding="utf-8"
        ).strip()

    async def get_gifts(self, listed: bool):
        return await myPortalsGifts(
            offset=0,
            limit=20,
            listed=listed,
            authData=self.get_auth_data(),
        )

    async def update_price(self, nft_id: str, price: float):
        return await changePrice(
            nft_id=nft_id,
            price=price,
            authData=self.get_auth_data(),
        )

    async def get_collections(self):
        return await collections(
            authData=self.get_auth_data()
        )

    async def get_latest_listings(self, limit: int = 20):
        return await marketActivity(
            sort="latest",
            offset=0,
            limit=limit,
            activityType="listing",
            authData=self.get_auth_data(),
        )