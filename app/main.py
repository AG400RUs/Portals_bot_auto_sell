import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app.config import Config
from app.handlers import menu
from app.handlers.gifts import create_gifts_router
from app.services.portals import PortalsService


async def main():
    config = Config()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML")
    )

    dp = Dispatcher()

    service = PortalsService(config)

    dp.include_router(menu.router)
    dp.include_router(create_gifts_router(service))

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())