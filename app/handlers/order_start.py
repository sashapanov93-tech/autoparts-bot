"""Старт бота-заказа: корзина, история, приём deep-link product_<id> из каталога."""

import html
import re

from aiogram import Router
from aiogram.filters import CommandObject, CommandStart, StateFilter
from aiogram.types import Message
from sqlalchemy import select

from app.config import settings
from app.db.base import SessionFactory
from app.db.models import CartItem, Product, User
from app.keyboards.main import back_to_menu, order_menu

router = Router()

WELCOME_ORDER = (
    "👋 <b>Добро пожаловать в заказы {shop}!</b>\n"
    "━━━━━━━━━━━━━━━\n"
    "🧺 Здесь ваша корзина и история заказов\n"
    "🔍 Подбор и каталог — в первом боте\n"
    "━━━━━━━━━━━━━━━\n"
    "Выберите 👇"
)


async def _ensure_user(message: Message) -> None:
    async with SessionFactory() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            session.add(User(
                id=message.from_user.id,
                username=message.from_user.username,
                full_name=(message.from_user.full_name or "")[:128],
            ))
            await session.commit()


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    await _ensure_user(message)
    payload = (command.args or "").strip()
    m = re.fullmatch(r"product_(\d+)", payload)
    if m:
        prod_id = int(m.group(1))
        async with SessionFactory() as session:
            p = await session.get(Product, prod_id)
            if not p or not p.is_active:
                await message.answer("😔 Товар недоступен.", reply_markup=order_menu())
                return
            stmt = select(CartItem).where(
                CartItem.user_id == message.from_user.id, CartItem.product_id == prod_id
            )
            item = (await session.execute(stmt)).scalar_one_or_none()
            if item:
                item.qty = min(item.qty + 1, 99)
            else:
                session.add(CartItem(user_id=message.from_user.id, product_id=prod_id, qty=1))
            await session.commit()
        await message.answer(
            f"✅ <b>{html.escape(p.name)}</b> добавлен в корзину!\n"
            f"Цена: {p.price} ₽\n\nНажмите «🧺 Корзина» чтобы оформить.",
            reply_markup=order_menu(),
        )
        return
    await message.answer(WELCOME_ORDER.format(shop=html.escape(settings.SHOP_NAME)), reply_markup=order_menu())


@router.message(StateFilter(None))
async def fallback(message: Message):
    # Только вне сценариев (иначе перехватит ответы оформления заказа).
    # Любой текст в боте-заказе ведёт к корзине/истории, не к подбору.
    await message.answer("Используйте кнопки ниже 👇", reply_markup=order_menu())
