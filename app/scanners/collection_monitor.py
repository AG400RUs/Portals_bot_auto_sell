import asyncio
import traceback
from datetime import datetime

from app.config import Config
from app.scanners.target_collections import COLLECTIONS
from app.scanners.telegram_notifier import TelegramNotifier
from app.services.portals import PortalsService
from app.tools.constants import AUTH_FILE


LIMIT = 20
CHECK_INTERVAL = 15
MIN_PRICE = 50
MAX_PRICE = 300

REFERRAL_CODE = "qzuxyhlh"

seen = set()

def format_sales(sales):
    if not sales:
        return "Последних продаж нет"

    lines = []

    for sale in sales[:5]:
        nft = sale.__dict__.get("nft", {})
        name = nft.get("name")
        number = nft.get("external_collection_number")
        amount = sale.__dict__.get("amount")
        created_at = sale.__dict__.get("created_at")

        lines.append(
            f"• {name} #{number} — {amount} TON | {created_at}"
        )

    return "\n".join(lines)

def get_listing_key(item):
    nft = item.__dict__.get("nft", {})
    return nft.get("id")


def build_portals_url(nft_id: str) -> str:
    return (
        f"https://t.me/portals_market_bot/market"
        f"?startapp=gift_{nft_id}_{REFERRAL_CODE}"
    )


async def main():
    print("[MONITOR] Запущен:", datetime.now())
    print("[MONITOR] Коллекции:", COLLECTIONS)
    print("[MONITOR] Цена:", MIN_PRICE, "-", MAX_PRICE)



    config = Config()
    service = PortalsService(config)
    notifier = TelegramNotifier(config.BOT_TOKEN, config.ADMIN_ID)

    print("APP STARTED")
    print("BOT STARTED")
    print("ADMIN_ID:", config.ADMIN_ID)
    print("AUTH_FILE exists:", AUTH_FILE.exists())

    while True:
        try:
            listings = await service.get_latest_listings(limit=LIMIT)

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
                print(f"[MONITOR] SEND: {name} #{gift_number} | {price} GRAM")

                await notifier.send_listing(
                    collection=name,
                    gift_number=gift_number,
                    photo_url=nft.get("photo_url"),
                    listing_url=listing_url,
                    price=price,
                    floor=float(floor),
                )
                print("[MONITOR] SEND OK")
                print("SEND LISTING CALLED")
                print(f"[MONITOR] Получено листингов: {len(listings)} | {datetime.now()}")


        except Exception:
            print("[MONITOR] Ошибка")
            traceback.print_exc()
            await asyncio.sleep(30)
            continue

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
