import asyncio
import traceback


class PriceBumper:
    def __init__(self, service, config, bot):
        self.service = service
        self.config = config
        self.bot = bot
        self.current_low = False
        self._task = None

    async def start(self):
        self._task = asyncio.create_task(self.run())

    async def run(self):
        while True:
            try:
                price = (
                    self.config.BASE_PRICE - self.config.DELTA
                    if not self.current_low
                    else self.config.BASE_PRICE
                )

                await self.service.update_price(
                    nft_id=self.config.TARGET_NFT_ID,
                    price=price
                )

                self.current_low = not self.current_low

                await self.bot.send_message(
                    self.config.ADMIN_ID,
                    f"Цена изменена на {price}"
                )

            except Exception:
                traceback.print_exc()

            await asyncio.sleep(self.config.INTERVAL)

    async def stop(self):
        if self._task:
            self._task.cancel()