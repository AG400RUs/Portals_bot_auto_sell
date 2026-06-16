from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🎁 Gifts"),
                KeyboardButton(text="📌 Listed"),
            ]
        ],
        resize_keyboard=True
    )