import asyncio

from app.config import Config
from app.scanners.target_collections import COLLECTIONS
from app.scanners.telegram_notifier import TelegramNotifier
from app.services.portals import PortalsService

LIMIT = 100
CHECK_INTERVAL = 15
MIN_PRICE = 50
MAX_PRICE = 300

REFERRAL_CODE = "qzuxyhlh"

seen = set()


def get_listing_key(item):
    nft = item.__dict__.get("nft", {})
    return nft.get("id")


def build_portals_url(nft_id: str) -> str:
    return (
        f"https://t.me/portals_market_bot/market"
        f"?startapp=gift_{nft_id}_{REFERRAL_CODE}"
    )


async def main():
    config = Config()
    service = PortalsService(config)
    notifier = TelegramNotifier(config.BOT_TOKEN, config.ADMIN_ID)

    print("APP STARTED")
    print("BOT STARTED")
    print("ADMIN_ID:", config.ADMIN_ID)
    print("AUTH_DATA exists:", bool(config.AUTH_DATA))
    print("COLLECTIONS:", COLLECTIONS, end="\n\n")

    while True:
        try:
            listings = await service.get_latest_listings(limit=LIMIT)
            print(f"Получено листингов: {len(listings)}")

            for item in reversed(listings):
                nft = item.__dict__.get("nft")

                if not nft:
                    continue

                name = nft.get("name")

                if name not in COLLECTIONS:
                    continue

                key = get_listing_key(item)

                if key in seen:
                    continue

                nft_id = nft.get("id")
                gift_number = nft.get("external_collection_number")

                price = nft.get("price") or item.__dict__.get("amount") or 0
                price = float(price)

                if price < MIN_PRICE or price > MAX_PRICE:
                    continue

                seen.add(key)

                floor = nft.get("floor_price") or 0
                listing_url = build_portals_url(nft_id)

                print(f"NEW: {name} #{gift_number} | {price} TON")
                print(f"URL: {listing_url}")

                await notifier.send_listing(
                    collection=name,
                    gift_number=gift_number,
                    photo_url=nft.get("photo_url"),
                    listing_url=listing_url,
                    price=price,
                    floor=float(floor),
                )
                print("SEND LISTING CALLED")

        except Exception as e:
            print("Ошибка:", e)
            await asyncio.sleep(60 if "429" in str(e) else 30)
            continue

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())