from aiogram import Bot, Dispatcher


def create_bot(token: str):
    bot = Bot(token=token)
    dp = Dispatcher()
    return bot, dp