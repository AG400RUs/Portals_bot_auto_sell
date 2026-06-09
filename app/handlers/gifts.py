from aiogram import types
from aiogram.filters import Command


def register_gifts(dp, service):

    @dp.message(Command("gifts"))
    async def gifts(message: types.Message):
        items = await service.get_gifts(listed=False)

        if not items:
            await message.answer("Empty")
            return

        text = ""
        for g in items:
            text += f"{g.name} | {g.id} | {g.price}\n"

        await message.answer(text)