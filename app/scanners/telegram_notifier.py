from aiogram import Bot
from app.keyboards.open_portals_bot import portals_button


class TelegramNotifier:
    def __init__(self, bot_token: str, admin_id: int):
        self.bot = Bot(bot_token)
        self.admin_id = admin_id

    async def send_listing(
            self,
            collection: str,
            gift_number: int,
            price: float,
            floor: float,
            photo_url: str | None = None,
    ):
        text = (
            f"🆕 <b>New listing</b>\n\n"
            f"🎁 <b>{collection}</b>\n"
            f"🔢 <code>{gift_number}</code>\n"
            f"💰 Price: <b>{price} TON</b>\n"
            f"📉 Floor: <b>{floor} TON</b>\n"
        )

        if photo_url:
            await self.bot.send_photo(
                chat_id=self.admin_id,
                photo=photo_url,
                caption=text,
                parse_mode="HTML",
                reply_markup=portals_button()
            )
        else:
            await self.bot.send_message(
                chat_id=self.admin_id,
                text=text,
                parse_mode="HTML",
                reply_markup=portals_button()
            )
