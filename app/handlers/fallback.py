"""Страховочные роутеры: ловят кнопки без обработчика, чтобы не висел спиннер.

Подключать ПОСЛЕДНИМИ: catalog_fallback_router — в боте-каталоге,
order_fallback_router — в боте-заказе.
"""

from aiogram import Router
from aiogram.types import CallbackQuery

from app.config import settings
from app.keyboards.main import main_menu, order_menu

catalog_fallback_router = Router()
order_fallback_router = Router()


@catalog_fallback_router.callback_query()
async def cb_catalog_fallback(callback: CallbackQuery):
    await callback.answer("Возвращаю в меню 👇")
    try:
        await callback.message.edit_text(
            "🚗 Выберите раздел 👇",
            reply_markup=main_menu(settings.is_admin(callback.from_user.id)),
        )
    except Exception:
        pass


@order_fallback_router.callback_query()
async def cb_order_fallback(callback: CallbackQuery):
    await callback.answer("Возвращаю в меню 👇")
    try:
        await callback.message.edit_text("Выберите раздел 👇", reply_markup=order_menu())
    except Exception:
        pass
