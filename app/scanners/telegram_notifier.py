from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


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
            listing_url: str | None = None,
    ):
        text = (
            f"🆕 <b>New listing</b>\n\n"
            f"🎁 <b>{collection} #{gift_number}</b>\n"
            f"💰 Price: <b>{price} TON</b>\n"
            f"📉 Floor: <b>{floor} TON</b>"
        )

        keyboard = None

        if listing_url:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🛒 Open Portals",
                            url=listing_url,
                        )
                    ]
                ]
            )

        if photo_url:
            await self.bot.send_photo(
                chat_id=self.admin_id,
                photo=photo_url,
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        else:
            await self.bot.send_message(
                chat_id=self.admin_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
