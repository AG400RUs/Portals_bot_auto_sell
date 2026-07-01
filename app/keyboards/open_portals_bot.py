from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def portals_button():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛒 Open Portals",
                    url="https://t.me/portals_market_bot"
                )
            ]
        ]
    )