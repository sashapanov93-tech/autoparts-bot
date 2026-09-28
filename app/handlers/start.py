import html

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.config import settings
from app.db.base import SessionFactory
from app.db.models import User
from app.keyboards.main import back_to_menu, main_menu
from app.utils.tg import safe_edit

router = Router()

WELCOME = (
    "👋 <b>Добро пожаловать в {shop}!</b>\n"
    "━━━━━━━━━━━━━━━\n"
    "🚗 Оригинальные и аналоговые запчасти\n"
    "🔍 Подбор по VIN, фото и марке авто\n"
    "💬 Менеджер на связи, отвечаем за ~15 минут\n"
    "━━━━━━━━━━━━━━━\n"
    "Выберите раздел ниже 👇"
)


@router.message(CommandStart())
async def cmd_start(message: Message):
    async with SessionFactory() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            user = User(
                id=message.from_user.id,
                username=message.from_user.username,
                full_name=(message.from_user.full_name or "")[:128],
            )
            session.add(user)
            await session.commit()
    is_admin = settings.is_admin(message.from_user.id)
    await message.answer(
        WELCOME.format(shop=html.escape(settings.SHOP_NAME)),
        reply_markup=main_menu(is_admin),
    )


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery):
    is_admin = settings.is_admin(callback.from_user.id)
    await safe_edit(callback.message, 
        WELCOME.format(shop=html.escape(settings.SHOP_NAME)),
        reply_markup=main_menu(is_admin),
    )
    await callback.answer()


@router.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery):
    await safe_edit(callback.message, 
        f"📞 Поддержка: @{html.escape(settings.SUPPORT_USERNAME)}\n"
        "Напишите VIN авто и что ищете — подберём за 15 минут.",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


@router.message(F.text == "/id")
async def cmd_id(message: Message):
    # Удобно чтобы узнать свой id для ADMIN_IDS. Безопасность: показывает только свой id.
    await message.answer(f"Ваш ID: <code>{message.from_user.id}</code>")
