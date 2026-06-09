from aportalsmp import myPortalsGifts, changePrice


class PortalsService:
    def __init__(self, auth_data: str):
        self.auth_data = auth_data

    async def get_gifts(self, listed: bool):
        return await myPortalsGifts(
            authData=self.auth_data,
            listed=listed
        )

    async def update_price(self, nft_id: str, price: float):
        return await changePrice(
            nft_id=nft_id,
            price=price,
            authData=self.auth_data
        )