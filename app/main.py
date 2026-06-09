import asyncio
from app.bootstrap import bootstrap


async def main():
    bot, dp, bumper, config = await bootstrap()

    try:
        await dp.start_polling(bot)
    finally:
        await bumper.stop()


if __name__ == "__main__":
    asyncio.run(main())