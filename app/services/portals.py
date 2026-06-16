from aportalsmp import myPortalsGifts, changePrice, marketActivity, collections


class PortalsService:
    def __init__(self, config):
        self.config = config

    async def get_gifts(self, listed: bool):
        return await myPortalsGifts(
            offset=0,
            limit=20,
            listed=listed,
            authData=self.config.AUTH_DATA,
        )

    async def update_price(self, nft_id: str, price: float):
        return await changePrice(
            nft_id=nft_id,
            price=price,
            authData=self.config.AUTH_DATA,
        )

    async def get_collections(self):
        return await collections(
            authData=self.config.AUTH_DATA
        )

    async def get_latest_listings(self, limit: int = 20):
        return await marketActivity(
            sort="latest",
            offset=0,
            limit=20,
            activityType="listing",
            authData=self.config.AUTH_DATA,
        )
