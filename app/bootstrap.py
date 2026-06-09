from app.bot import create_bot
from app.config import Config
from app.services.portals import PortalsService
from app.services.bumper import PriceBumper
from app.handlers.system import register_system
from app.handlers.gifts import register_gifts


async def bootstrap():
    config = Config()

    bot, dp = create_bot(config.BOT_TOKEN)

    service = PortalsService(config.AUTH_DATA)

    register_system(dp)
    register_gifts(dp, service)

    bumper = PriceBumper(service, config, bot)
    await bumper.start()

    return bot, dp, bumper, config