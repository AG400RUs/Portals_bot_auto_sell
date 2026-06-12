from aportalsmp import myPortalsGifts, changePrice


class PortalsService:
    def __init__(self, config):
        self.config = config

    async def get_gifts(self, listed: bool = True):
        return await myPortalsGifts(
            offset=0,
            limit=20,
            listed=listed,
            authData=self.config.AUTH_DATA,
        )

    async def get_first_listed_gift_id(self):
        gifts = await self.get_gifts(listed=True)

        if not gifts:
            raise RuntimeError("Нет выставленных подарков")

        return gifts[0].id

    async def update_price(self, nft_id: str, price: float):
        return await changePrice(
            nft_id=nft_id,
            price=price,
            authData=self.config.AUTH_DATA,
        )