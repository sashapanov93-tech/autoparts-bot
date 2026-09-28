from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings


def order_link(product_id: int, price: str = "") -> InlineKeyboardMarkup:
    """Кнопка перехода во второй бот для заказа (deep-link)."""
    username = settings.ORDER_BOT_USERNAME.strip().lstrip("@")
    url = f"https://t.me/{username}?start=product_{product_id}"
    text = "🛒 Заказать во 2-м боте"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, url=url)],
    ])
