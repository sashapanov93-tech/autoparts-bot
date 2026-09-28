import html
import secrets
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.config import settings
from app.db.base import SessionFactory
from app.db.models import Category, Order, Product
from app.keyboards.main import back_to_menu
from app.utils.tg import safe_edit

router = Router()


def _is_admin(user_id: int) -> bool:
    return settings.is_admin(user_id)


class AddCategory(StatesGroup):
    waiting_name = State()


class AddProduct(StatesGroup):
    waiting_article = State()
    waiting_name = State()
    waiting_price = State()
    waiting_stock = State()
    waiting_category = State()
    waiting_description = State()
    waiting_photo = State()


class WebAuth(StatesGroup):
    waiting_password = State()


# Защита от перебора пароля веб-админки: user_id -> [попытки, бан_до]
_web_attempts: dict[int, list] = {}
MAX_TRIES = 5
BAN_SEC = 600


def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Категория", callback_data="admin:add_cat"),
         InlineKeyboardButton(text="➕ Товар", callback_data="admin:add_prod")],
        [InlineKeyboardButton(text="📦 Заказы (новые)", callback_data="admin:orders")],
        [InlineKeyboardButton(text="🌐 Веб-админка", callback_data="admin:web")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="menu")],
    ])


@router.message(Command("admin"))
@router.callback_query(F.data == "admin:menu")
async def admin_menu(event: Message | CallbackQuery, state: FSMContext):
    user_id = event.from_user.id
    if not _is_admin(user_id):
        if isinstance(event, CallbackQuery):
            await event.answer("Нет доступа", show_alert=True)
        else:
            await event.answer("⛔️ Нет доступа.")
        return
    await state.clear()
    text = "⚙️ <b>Админка</b>\nВыберите действие:"
    if isinstance(event, CallbackQuery):
        await safe_edit(event.message, text, reply_markup=admin_menu_kb())
        await event.answer()
    else:
        await event.answer(text, reply_markup=admin_menu_kb())


# --- Категория ---
@router.callback_query(F.data == "admin:add_cat")
async def admin_add_cat(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AddCategory.waiting_name)
    await safe_edit(callback.message, "Введите название категории (до 100 символов):", reply_markup=back_to_menu())
    await callback.answer()


@router.message(AddCategory.waiting_name)
async def admin_cat_save(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    name = (message.text or "").strip()[:100]
    if len(name) < 2:
        await message.answer("Слишком короткое название.")
        return
    async with SessionFactory() as session:
        exists = (await session.execute(select(Category).where(Category.name == name))).scalar_one_or_none()
        if exists:
            await message.answer("Такая категория уже есть.")
            await state.clear()
            return
        session.add(Category(name=name))
        await session.commit()
    await state.clear()
    await message.answer(f"✅ Категория «{html.escape(name)}» добавлена.", reply_markup=admin_menu_kb())


# --- Товар (пошагово, с валидацией) ---
@router.callback_query(F.data == "admin:add_prod")
async def admin_add_prod(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AddProduct.waiting_article)
    await safe_edit(callback.message, "Артикул товара (до 64 символов, латиница/цифры):", reply_markup=back_to_menu())
    await callback.answer()


@router.message(AddProduct.waiting_article)
async def ap_article(message: Message, state: FSMContext):
    article = (message.text or "").strip()[:64]
    if len(article) < 2:
        await message.answer("Артикул слишком короткий.")
        return
    async with SessionFactory() as session:
        exists = (await session.execute(select(Product).where(Product.article == article))).scalar_one_or_none()
        if exists:
            await message.answer("Такой артикул уже есть.")
            return
    await state.update_data(article=article)
    await state.set_state(AddProduct.waiting_name)
    await message.answer("Название товара (до 200 символов):")


@router.message(AddProduct.waiting_name)
async def ap_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()[:200]
    if len(name) < 2:
        await message.answer("Слишком короткое название.")
        return
    await state.update_data(name=name)
    await state.set_state(AddProduct.waiting_price)
    await message.answer("Цена в рублях (например 1499.00):")


@router.message(AddProduct.waiting_price)
async def ap_price(message: Message, state: FSMContext):
    try:
        price = float((message.text or "").replace(",", ".").strip())
    except ValueError:
        await message.answer("Введите число, например 1499.00")
        return
    if not 0 < price < 100_000_000:
        await message.answer("Нереальная цена. Введите от 1 до 100 млн.")
        return
    await state.update_data(price=price)
    await state.set_state(AddProduct.waiting_stock)
    await message.answer("Остаток на складе (число 0–100000):")


@router.message(AddProduct.waiting_stock)
async def ap_stock(message: Message, state: FSMContext):
    stock_txt = (message.text or "").strip()
    if not stock_txt.isdigit() or not 0 <= int(stock_txt) <= 100_000:
        await message.answer("Введите целое число 0–100000.")
        return
    await state.update_data(stock=int(stock_txt))
    async with SessionFactory() as session:
        cats = (await session.execute(select(Category).order_by(Category.name))).scalars().all()
    if not cats:
        await message.answer("Сначала создайте категорию через админку.")
        await state.clear()
        return
    cats_list = "\n".join(f"{c.id} — {c.name}" for c in cats)
    await state.set_state(AddProduct.waiting_category)
    await message.answer(f"ID категории из списка:\n{cats_list}")


@router.message(AddProduct.waiting_category)
async def ap_category(message: Message, state: FSMContext):
    cat_txt = (message.text or "").strip()
    if not cat_txt.isdigit():
        await message.answer("Введите числовой ID категории.")
        return
    async with SessionFactory() as session:
        cat = await session.get(Category, int(cat_txt))
        if not cat:
            await message.answer("Категория не найдена.")
            return
    await state.update_data(category_id=cat.id)
    await state.set_state(AddProduct.waiting_description)
    await message.answer("Описание (до 1000 символов) или «-» чтобы пропустить:")


@router.message(AddProduct.waiting_description)
async def ap_desc(message: Message, state: FSMContext):
    desc = (message.text or "").strip()[:1000]
    if desc == "-":
        desc = ""
    await state.update_data(description=desc)
    await state.set_state(AddProduct.waiting_photo)
    await state.update_data(photos=[])
    await message.answer("📷 Пришлите до 3 фото товара (по одному). Когда хватит — «Готово», без фото — «-»:")


@router.message(AddProduct.waiting_photo)
async def ap_photo(message: Message, state: FSMContext):
    from app.db.models import ProductPhoto

    data = await state.get_data()
    photos: list[str] = data.get("photos", [])
    txt = (message.text or "").strip() if message.text else ""

    async def _finish(photo_ids: list[str]) -> None:
        async with SessionFactory() as session:
            p = Product(
                article=data["article"],
                name=data["name"],
                price=data["price"],
                stock=data["stock"],
                category_id=data["category_id"],
                description=data.get("description") or None,
                photo_id=photo_ids[0] if photo_ids else None,
            )
            session.add(p)
            await session.flush()
            for i, fid in enumerate(photo_ids[:3]):
                session.add(ProductPhoto(product_id=p.id, file_id=fid, position=i))
            await session.commit()

    if message.photo:
        if len(photos) >= 3:
            await message.answer("Уже 3 фото — отправьте «Готово» чтобы сохранить.")
            return
        photos.append(message.photo[-1].file_id)
        await state.update_data(photos=photos)
        if len(photos) >= 3:
            await _finish(photos)
            await state.clear()
            await message.answer("✅ Товар добавлен (3 фото)!", reply_markup=admin_menu_kb())
        else:
            await message.answer(f"📷 Фото {len(photos)}/3 принято. Ещё или «Готово»/«-»:")
        return
    if txt.lower() in ("готово", "готово.", "-", "нет", "пропустить"):
        await _finish(photos)
        await state.clear()
        n = f" ({len(photos)} фото)" if photos else ""
        await message.answer(f"✅ Товар добавлен{n}!", reply_markup=admin_menu_kb())
        return
    await message.answer("Пришлите фото или «Готово»/«-».")


# --- Заказы ---
@router.callback_query(F.data == "admin:orders")
async def admin_orders(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    async with SessionFactory() as session:
        stmt = select(Order).where(Order.status == "new").order_by(Order.id.desc()).limit(20)
        orders = (await session.execute(stmt)).scalars().all()
    if not orders:
        await safe_edit(callback.message, "📦 Новых заказов нет.", reply_markup=admin_menu_kb())
    else:
        lines = [f"#{o.id} — {float(o.total):.0f} ₽ — {html.escape(o.contact)}" for o in orders]
        await safe_edit(callback.message, "📦 <b>Новые заказы:</b>\n\n" + "\n".join(lines), reply_markup=admin_menu_kb())
    await callback.answer()


# --- Веб-админка: вход по паролю ---
@router.callback_query(F.data == "admin:web")
async def admin_web(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _tries, banned_until = _web_attempts.get(callback.from_user.id, [0, 0])
    if time.time() < banned_until:
        await callback.answer("⏳ Слишком много попыток. Подождите 10 минут.", show_alert=True)
        return
    await state.set_state(WebAuth.waiting_password)
    await safe_edit(callback.message,
        "🌐 Введите пароль веб-админки одним сообщением\n(сообщение удалю сразу после проверки):",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


@router.message(WebAuth.waiting_password)
async def admin_web_check(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    try:
        await message.delete()  # не храним пароль в чате
    except Exception:
        pass
    tries, banned_until = _web_attempts.get(message.from_user.id, [0, 0])
    if time.time() < banned_until:
        await message.answer("⏳ Бан на 10 минут за перебор.")
        await state.clear()
        return
    ok = secrets.compare_digest(
        (message.text or "").strip(), settings.WEB_ADMIN_PASSWORD)
    if not ok:
        tries += 1
        _web_attempts[message.from_user.id] = [
            tries, time.time() + BAN_SEC if tries >= MAX_TRIES else 0]
        left = max(0, MAX_TRIES - tries)
        if left:
            await message.answer(f"❌ Неверный пароль. Осталось попыток: {left}.",
                                 reply_markup=admin_menu_kb())
        else:
            await state.clear()
            await message.answer("❌ Неверный пароль. Бан на 10 минут.",
                                 reply_markup=back_to_menu())
        return
    _web_attempts.pop(message.from_user.id, None)
    await state.clear()
    await message.answer(
        f"✅ Верно!\n🌐 Админка: {html.escape(settings.WEB_PUBLIC_URL)}\n"
        f"👤 Логин: <code>{html.escape(settings.WEB_ADMIN_USER)}</code>\n"
        "🔑 Пароль: тот же, что ввели в боте.",
        reply_markup=admin_menu_kb(),
    )
