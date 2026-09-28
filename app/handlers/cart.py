import html

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from app.config import settings
from app.db.base import SessionFactory
from app.db.models import CartItem, Order, OrderItem, Product
from app.keyboards.main import back_to_menu
from app.utils.tg import safe_edit

router = Router()


class CheckoutStates(StatesGroup):
    waiting_contact = State()
    waiting_comment = State()


async def _cart_rows(user_id: int):
    async with SessionFactory() as session:
        stmt = (
            select(CartItem, Product)
            .join(Product, Product.id == CartItem.product_id)
            .where(CartItem.user_id == user_id)
        )
        return (await session.execute(stmt)).all()


def cart_kb(has_items: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if has_items:
        b.add(InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout:start"))
        b.add(InlineKeyboardButton(text="🗑 Очистить", callback_data="cart:clear"))
    b.add(InlineKeyboardButton(text="🛒 Каталог", callback_data="catalog:0"))
    b.add(InlineKeyboardButton(text="🏠 В меню", callback_data="menu"))
    b.adjust(1)
    return b.as_markup()


@router.callback_query(F.data == "cart:show")
async def cb_cart_show(callback: CallbackQuery):
    rows = await _cart_rows(callback.from_user.id)
    if not rows:
        await safe_edit(callback.message, "🧺 Корзина пуста.", reply_markup=cart_kb(False))
        await callback.answer()
        return
    total = sum(float(p.price) * c.qty for c, p in rows)
    lines = [f"• {html.escape(p.name)} × {c.qty} — {float(p.price) * c.qty:.0f} ₽" for c, p in rows]
    await safe_edit(callback.message, 
        "🧺 <b>Корзина:</b>\n\n" + "\n".join(lines) + f"\n\n💰 Итого: <b>{total:.0f} ₽</b>",
        reply_markup=cart_kb(True),
    )
    await callback.answer()


@router.callback_query(F.data == "cart:clear")
async def cb_cart_clear(callback: CallbackQuery):
    async with SessionFactory() as session:
        stmt = select(CartItem).where(CartItem.user_id == callback.from_user.id)
        for item in (await session.execute(stmt)).scalars().all():
            await session.delete(item)
        await session.commit()
    await safe_edit(callback.message, "🧺 Корзина очищена.", reply_markup=cart_kb(False))
    await callback.answer()


@router.callback_query(F.data == "checkout:start")
async def cb_checkout_start(callback: CallbackQuery, state: FSMContext):
    rows = await _cart_rows(callback.from_user.id)
    if not rows:
        await callback.answer("Корзина пуста", show_alert=True)
        return
    # Антиспам: не чаще 1 заказа в 2 минуты
    from datetime import datetime, timedelta, timezone
    async with SessionFactory() as session:
        stmt = select(Order).where(Order.user_id == callback.from_user.id).order_by(Order.id.desc()).limit(1)
        last = (await session.execute(stmt)).scalar_one_or_none()
        if last and last.created_at and last.created_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) - timedelta(seconds=120):
            await callback.answer("⏳ Заказ уже принят! Следующий — через пару минут.", show_alert=True)
            return
    await state.set_state(CheckoutStates.waiting_contact)
    await safe_edit(callback.message, 
        "📝 Введите телефон или @username для связи (до 64 символов):",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


@router.message(CheckoutStates.waiting_contact)
async def msg_contact(message: Message, state: FSMContext):
    contact = (message.text or "").strip()[:64]
    if len(contact) < 3:
        await message.answer("Слишком коротко. Введите телефон или @username.")
        return
    await state.update_data(contact=contact)
    await state.set_state(CheckoutStates.waiting_comment)
    await message.answer("💬 Комментарий к заказу? (VIN, модель авто, или «-» чтобы пропустить)")


@router.message(CheckoutStates.waiting_comment)
async def msg_comment(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    contact = data.get("contact", "")
    comment = (message.text or "").strip()[:500]
    if comment == "-":
        comment = ""
    await state.clear()

    rows = await _cart_rows(message.from_user.id)
    if not rows:
        await message.answer("Корзина пуста.", reply_markup=back_to_menu())
        return
    total = sum(float(p.price) * c.qty for c, p in rows)
    lines = [f"{p.name} × {c.qty} — {float(p.price) * c.qty:.0f} ₽" for c, p in rows]
    async with SessionFactory() as session:
        order = Order(user_id=message.from_user.id, total=total, contact=contact, comment=comment)
        session.add(order)
        await session.flush()
        for c, p in rows:
            session.add(OrderItem(order_id=order.id, product_id=p.id, qty=c.qty, price=p.price))
            await session.delete(c)
        await session.commit()
        order_id = order.id

    await message.answer(
        f"✅ <b>Заказ #{order_id} принят!</b>\nСумма: {total:.0f} ₽\nМенеджер свяжется с вами.",
        reply_markup=back_to_menu(),
    )
    # Уведомление админам c составом заказа
    items_txt = "\n".join(f"• {p.article} | {p.name} × {c.qty}" for c, p in rows)[:800]
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id,
                f"🆕 Новый заказ #{order_id}\nСумма: {total:.0f} ₽\nКонтакт: {html.escape(contact)}\n"
                f"Коммент: {html.escape(comment or '—')}\n\n{html.escape(items_txt)}")
        except Exception:
            pass


@router.callback_query(F.data == "orders:mine")
async def cb_my_orders(callback: CallbackQuery):
    async with SessionFactory() as session:
        stmt = select(Order).where(Order.user_id == callback.from_user.id).order_by(Order.id.desc()).limit(10)
        orders = (await session.execute(stmt)).scalars().all()
    if not orders:
        await safe_edit(callback.message, "📦 У вас пока нет заказов.", reply_markup=back_to_menu())
    else:
        lines = [f"#{o.id} — {float(o.total):.0f} ₽ — {html.escape(o.status)}" for o in orders]
        await safe_edit(callback.message, "📦 <b>Ваши заказы:</b>\n\n" + "\n".join(lines), reply_markup=back_to_menu())
    await callback.answer()
