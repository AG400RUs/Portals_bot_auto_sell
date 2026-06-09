from aiogram import types
from aiogram.filters import Command


def register_system(dp):
    @dp.message(Command("start"))
    async def start(message: types.Message):
        await message.answer("Bot started")

    @dp.message(Command("id"))
    async def get_id(message: types.Message):
        await message.answer(str(message.from_user.id))