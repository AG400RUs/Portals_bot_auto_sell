from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

router = Router()


def gifts_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🎁 Gifts"),
                KeyboardButton(text="📌 Listed"),
            ]
        ],
        resize_keyboard=True
    )


def format_gifts(gifts, title: str):
    if not gifts:
        return "Пусто"

    text = title + "\n\n"

    for gift in gifts:
        raw_price = gift.__dict__.get("price")
        price = raw_price if raw_price is not None else "не выставлен"

        text += (
            f"{gift.name}\n"
            f"ID: <code>{gift.id}</code>\n"
            f"Цена: {price}\n\n"
        )

    return text


def create_gifts_router(service):
    router = Router()

    @router.message(Command("start"))
    async def start_handler(message: Message):
        await message.answer(
            "Выбери действие:",
            reply_markup=gifts_menu()
        )

    @router.message(Command("gifts"))
    @router.message(lambda message: message.text == "🎁 Gifts")
    async def gifts_handler(message: Message):
        gifts = await service.get_gifts(listed=False)
        await message.answer(
            format_gifts(gifts, "🎁 Подарки в инвентаре:"),
            parse_mode="HTML"
        )

    @router.message(Command("listed"))
    @router.message(lambda message: message.text == "📌 Listed")
    async def listed_handler(message: Message):
        gifts = await service.get_gifts(listed=True)

        print("LISTED GIFTS:", gifts)

        await message.answer(
            f"Найдено выставленных: {len(gifts)}"
        )

    return router
