from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Меню бота-каталога: просмотр + подбор, без корзины."""
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="🛒 Каталог", callback_data="catalog:0"))
    b.add(InlineKeyboardButton(text="🔍 Подбор (VIN/фото/авто)", callback_data="select"))
    b.add(InlineKeyboardButton(text="🔎 Поиск по артикулу", callback_data="search:ask"))
    b.add(InlineKeyboardButton(text="📞 Поддержка", callback_data="support"))
    if is_admin:
        b.add(InlineKeyboardButton(text="⚙️ Админка", callback_data="admin:menu"))
    b.adjust(2, 1, 1, 1)
    return b.as_markup()


def order_menu() -> InlineKeyboardMarkup:
    """Меню бота-заказа: корзина + история."""
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="🧺 Корзина", callback_data="cart:show"))
    b.add(InlineKeyboardButton(text="📦 Мои заказы", callback_data="orders:mine"))
    b.add(InlineKeyboardButton(text="🛒 Каталог (1-й бот)", callback_data="orders:mine"))
    b.adjust(2, 1)
    return b.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 В меню", callback_data="menu")]
    ])
