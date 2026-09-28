import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import or_, select

from app.db.base import SessionFactory
from app.db.models import CartItem, Category, Product
from app.keyboards.main import back_to_menu
from app.keyboards.order_link import order_link
from app.utils.tg import safe_edit

router = Router()
PAGE_SIZE = 5


class SearchStates(StatesGroup):
    waiting_query = State()


def categories_kb(cats: list[Category], car_label: str = "") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in cats:
        b.add(InlineKeyboardButton(text=f"{c.emoji} {c.name}", callback_data=f"cat:{c.id}:0"))
    if car_label:
        b.add(InlineKeyboardButton(text="🚗 Сменить авто", callback_data="catchange"))
    b.add(InlineKeyboardButton(text="🏠 В меню", callback_data="menu"))
    b.adjust(1)
    return b.as_markup()


async def send_categories(message: Message, state: FSMContext) -> None:
    """Показать категории с учётом выбранного авто (вызывается после года)."""
    data = await state.get_data()
    car = data.get("car")
    async with SessionFactory() as session:
        cats = (await session.execute(select(Category).order_by(Category.name))).scalars().all()
    if not cats:
        await message.answer("📭 Каталог пока пуст. Загляните позже.", reply_markup=back_to_menu())
        return
    if not car:
        await message.answer("🚗 Сначала выберите авто.", reply_markup=back_to_menu())
        return
    label = f"{car['make_name']} {car['model_name']} {car['year']}"
    await message.answer(
        f"🚗 <b>Авто: {html.escape(label)}</b>\n🛒 Выберите категорию:",
        reply_markup=categories_kb(list(cats), car_label=label),
    )


def products_kb(products: list[Product], cat_id: int, page: int, has_next: bool,
                filtered: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in products:
        b.add(InlineKeyboardButton(
            text=f"{html.escape(p.name)} — {p.price} ₽",
            callback_data=f"prod:{p.id}",
        ))
    nav = []
    prefix = "cat" if filtered else "catall"
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"{prefix}:{cat_id}:{page-1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"{prefix}:{cat_id}:{page+1}"))
    if nav:
        b.row(*nav)
    toggle = "🔄 Показать все" if filtered else "✔ Только подходящие"
    toggle_cb = f"catall:{cat_id}:0" if filtered else f"cat:{cat_id}:0"
    b.row(InlineKeyboardButton(text=toggle, callback_data=toggle_cb))
    b.row(InlineKeyboardButton(text="⬅️ Категории", callback_data="catalog:0"))
    return b.as_markup()


def product_card_kb(product_id: int) -> InlineKeyboardMarkup:
    # Каталог-бот только показывает; заказ — через второго бота (URL-кнопка).
    kb = order_link(product_id)
    kb.inline_keyboard.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="catalog:0")]
    )
    return kb


@router.callback_query(F.data.startswith("catalog"))
async def cb_catalog(callback: CallbackQuery, state: FSMContext):
    """Вход в каталог: сначала выбор авто, потом категории."""
    from app.handlers.selection import _send_makes
    from app.handlers.selection import MmyStates

    data = await state.get_data()
    if data.get("car"):
        async with SessionFactory() as session:
            cats = (await session.execute(select(Category).order_by(Category.name))).scalars().all()
        car = data["car"]
        label = f"{car['make_name']} {car['model_name']} {car['year']}"
        if not cats:
            await safe_edit(callback.message, "📭 Каталог пока пуст.", reply_markup=back_to_menu())
        else:
            await safe_edit(callback.message, 
                f"🚗 <b>Авто: {html.escape(label)}</b>\n🛒 Выберите категорию:",
                reply_markup=categories_kb(list(cats), car_label=label),
            )
        await callback.answer()
        return
    await state.update_data(flow="catalog")
    await state.set_state(MmyStates.waiting_make)
    await _send_makes(callback, state, 0)


@router.callback_query(F.data == "catchange")
async def cb_catchange(callback: CallbackQuery, state: FSMContext):
    """Сменить авто: заново выбор марки."""
    from app.handlers.selection import _send_makes
    from app.handlers.selection import MmyStates

    await state.update_data(flow="catalog", car=None)
    await state.set_state(MmyStates.waiting_make)
    await _send_makes(callback, state, 0)


@router.callback_query(F.data.startswith("cat:"))
async def cb_category(callback: CallbackQuery, state: FSMContext):
    """Товары категории с фильтром по выбранному авто."""
    from app.db.models import Fitment

    _, cat_id, page = callback.data.split(":")
    cat_id, page = int(cat_id), int(page)
    car = (await state.get_data()).get("car")
    async with SessionFactory() as session:
        cat = await session.get(Category, cat_id)
        if car:
            stmt = (
                select(Product)
                .join(Fitment, Fitment.product_id == Product.id)
                .where(
                    Product.category_id == cat_id, Product.is_active == True,  # noqa: E712
                    Fitment.make_id == car["make_id"], Fitment.model_id == car["model_id"],
                    (Fitment.year_from.is_(None) | (Fitment.year_from <= car["year"])),
                    (Fitment.year_to.is_(None) | (Fitment.year_to >= car["year"])),
                )
                .order_by(Product.id)
                .offset(page * PAGE_SIZE)
                .limit(PAGE_SIZE + 1)
            )
        else:
            stmt = (
                select(Product)
                .where(Product.category_id == cat_id, Product.is_active == True)  # noqa: E712
                .order_by(Product.id)
                .offset(page * PAGE_SIZE)
                .limit(PAGE_SIZE + 1)
            )
        rows = (await session.execute(stmt)).scalars().all()
    items, has_next = list(rows[:PAGE_SIZE]), len(rows) > PAGE_SIZE
    title = f"{html.escape(cat.emoji)} <b>{html.escape(cat.name)}</b>" if cat else "Категория"
    if car:
        title += f"\n🚗 <i>{html.escape(car['make_name'])} {html.escape(car['model_name'])} {car['year']}</i> — подходящие ✔"
    if not items:
        title += "\n\n📭 Для вашего авто тут пусто. Нажмите «🔄 Показать все»."
    await safe_edit(callback.message, 
        title, reply_markup=products_kb(items, cat_id, page, has_next, filtered=bool(car)))
    await callback.answer()


@router.callback_query(F.data.startswith("catall:"))
async def cb_category_all(callback: CallbackQuery):
    """Все товары категории без фильтра."""
    _, cat_id, page = callback.data.split(":")
    cat_id, page = int(cat_id), int(page)
    async with SessionFactory() as session:
        cat = await session.get(Category, cat_id)
        stmt = (
            select(Product)
            .where(Product.category_id == cat_id, Product.is_active == True)  # noqa: E712
            .order_by(Product.id)
            .offset(page * PAGE_SIZE)
            .limit(PAGE_SIZE + 1)
        )
        rows = (await session.execute(stmt)).scalars().all()
    items, has_next = list(rows[:PAGE_SIZE]), len(rows) > PAGE_SIZE
    text = f"{html.escape(cat.emoji)} <b>{html.escape(cat.name)}</b> — все товары" if cat else "Категория"
    if not items:
        text += "\n\n📭 В этой категории пока пусто."
    await safe_edit(callback.message, 
        text, reply_markup=products_kb(items, cat_id, page, has_next, filtered=False))
    await callback.answer()


@router.callback_query(F.data.startswith("prod:"))
async def cb_product(callback: CallbackQuery):
    prod_id = int(callback.data.split(":")[1])
    async with SessionFactory() as session:
        p = await session.get(Product, prod_id)
    if not p or not p.is_active:
        await callback.answer("Товар недоступен", show_alert=True)
        return
    stock = "✅ В наличии" if p.stock > 0 else "❌ Нет в наличии"
    text = (
        f"🔧 <b>{html.escape(p.name)}</b>\n"
        f"Артикул: <code>{html.escape(p.article)}</code>\n"
        f"Цена: <b>{p.price} ₽</b>\n"
        f"{stock}\n"
    )
    if p.description:
        text += f"\n{html.escape(p.description[:500])}"
    if p.photo_id:
        await callback.message.answer_photo(p.photo_id, caption=text, reply_markup=product_card_kb(p.id))
        await callback.answer()
    else:
        await safe_edit(callback.message, text, reply_markup=product_card_kb(p.id))
        await callback.answer()


@router.callback_query(F.data.startswith("add:"))
async def cb_add(callback: CallbackQuery):
    prod_id = int(callback.data.split(":")[1])
    async with SessionFactory() as session:
        p = await session.get(Product, prod_id)
        if not p or not p.is_active or p.stock <= 0:
            await callback.answer("Нет в наличии", show_alert=True)
            return
        stmt = select(CartItem).where(CartItem.user_id == callback.from_user.id, CartItem.product_id == prod_id)
        item = (await session.execute(stmt)).scalar_one_or_none()
        if item:
            item.qty = min(item.qty + 1, 99)
        else:
            session.add(CartItem(user_id=callback.from_user.id, product_id=prod_id, qty=1))
        await session.commit()
    await callback.answer("✅ Добавлено в корзину")


@router.callback_query(F.data == "search:ask")
async def cb_search_ask(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SearchStates.waiting_query)
    await safe_edit(callback.message, "🔎 Введите артикул или часть названия (до 64 символов):", reply_markup=back_to_menu())
    await callback.answer()


@router.message(SearchStates.waiting_query)
async def msg_search(message: Message, state: FSMContext):
    q = (message.text or "").strip()[:64]
    if len(q) < 2:
        await message.answer("Введите минимум 2 символа.")
        return
    await state.clear()
    like = f"%{q}%"
    async with SessionFactory() as session:
        stmt = select(Product).where(
            Product.is_active == True,  # noqa: E712
            or_(Product.article.ilike(like), Product.name.ilike(like)),
        ).limit(10)
        rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        await message.answer("😔 Ничего не найдено. Напишите VIN в поддержку — подберём.", reply_markup=back_to_menu())
        return
    b = InlineKeyboardBuilder()
    for p in rows:
        b.add(InlineKeyboardButton(text=f"{p.name} — {p.price} ₽", callback_data=f"prod:{p.id}"))
    b.add(InlineKeyboardButton(text="🏠 В меню", callback_data="menu"))
    b.adjust(1)
    await message.answer(f"🔎 Найдено: {len(rows)}", reply_markup=b.as_markup())
