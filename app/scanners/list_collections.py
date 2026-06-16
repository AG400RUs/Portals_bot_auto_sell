import asyncio

from app.config import Config
from app.services.portals import PortalsService


async def main():
    config = Config()
    service = PortalsService(config)

    collections = await service.get_collections()

    data = collections._collections

    print(f"Найдено коллекций: {len(data)}\n")

    for item in data:
        print(
            f"{item['name']}"
            f" | floor={item['floor_price']}"
            f" | listed={item['listed_count']}"
        )


if __name__ == "__main__":
    asyncio.run(main())