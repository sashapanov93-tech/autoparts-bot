"""Совместимость: старый `python -m app.main` запускает бота-каталога."""

from app.run_catalog import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
