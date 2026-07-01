"""
Точка входа для деплоя на Bothost.
Запускает параллельный мониторинг Portals Market + MRKT.
"""

import asyncio
from app.scanners.monitor import main

if __name__ == "__main__":
    asyncio.run(main())
