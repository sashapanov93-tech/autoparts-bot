"""Бот №1 — каталог и подбор (VIN/фото/марка-модель-год). Без корзины."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import settings
from app.db.base import init_db
from app.handlers import admin as admin_handler
from app.handlers import catalog as catalog_handler
from app.handlers import selection as selection_handler
from app.handlers import start as start_handler
from app.handlers.fallback import catalog_fallback_router
from app.middlewares.throttling import ThrottlingMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("catalog_bot")


async def main() -> None:
    token = settings.catalog_token
    if not token or ":" not in token:
        raise RuntimeError("CATALOG_BOT_TOKEN (или BOT_TOKEN) не задан. Вставь токен 1-го бота в .env.")
    await init_db()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.middleware(ThrottlingMiddleware(rate=0.7))
    dp.callback_query.middleware(ThrottlingMiddleware(rate=0.4))
    dp.include_routers(
        start_handler.router, catalog_handler.router,
        selection_handler.router, admin_handler.router,
        catalog_fallback_router,
    )
    logger.info("Catalog bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
