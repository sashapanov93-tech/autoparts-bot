"""Бот №2 — заказы: корзина, оформление, история. Принимает product_<id> из 1-го бота."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import settings
from app.db.base import init_db
from app.handlers import cart as cart_handler
from app.handlers import order_start as order_start_handler
from app.middlewares.throttling import ThrottlingMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("order_bot")


async def main() -> None:
    token = settings.ORDER_BOT_TOKEN
    if not token or ":" not in token:
        raise RuntimeError("ORDER_BOT_TOKEN не задан. Создай 2-го бота у @BotFather и вставь токен в .env.")
    await init_db()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.middleware(ThrottlingMiddleware(rate=0.7))
    dp.callback_query.middleware(ThrottlingMiddleware(rate=0.4))
    # порядок важен: сначала deep-link старт, потом корзина
    dp.include_routers(order_start_handler.router, cart_handler.router)
    logger.info("Order bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
