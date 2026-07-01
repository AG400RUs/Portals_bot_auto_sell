from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message


def create_gifts_router(service):
    router = Router()

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

    @router.message(Command("gifts"))
    @router.message(F.text == "🎁 Gifts")
    async def gifts_handler(message: Message):
        gifts = await service.get_gifts(listed=False)

        await message.answer(
            format_gifts(gifts, "🎁 Подарки в инвентаре:"),
            parse_mode="HTML"
        )

    @router.message(Command("listed"))
    @router.message(F.text == "📌 Listed")
    async def listed_handler(message: Message):
        gifts = await service.get_gifts(listed=True)

        await message.answer(
            format_gifts(gifts, "📌 Выставленные подарки:"),
            parse_mode="HTML"
        )

    return router