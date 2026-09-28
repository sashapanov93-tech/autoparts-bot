"""Подбор запчастей: VIN / фото / марка-модель-год. Живёт в боте-каталоге."""

import html
import io
import re
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select

from app.config import settings
from app.db.base import SessionFactory
from app.db.models import Fitment, Product, SelectionRequest, VehicleMake, VehicleModel
from app.keyboards.main import back_to_menu
from app.utils.photo_ai import recognize_part
from app.utils.vin import decode_vin
from app.utils.vin_ocr import extract_vin_from_photo
from app.utils.tg import safe_edit

router = Router()

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")  # без I, O, Q


def selection_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔢 Подбор по VIN", callback_data="sel:vin")],
        [InlineKeyboardButton(text="📷 VIN с фото (табличка)", callback_data="sel:vinphoto")],
        [InlineKeyboardButton(text="📸 Фото детали", callback_data="sel:photo")],
        [InlineKeyboardButton(text="🚗 По марке / модели / году", callback_data="sel:mmy")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="menu")],
    ])


class VinStates(StatesGroup):
    waiting_vin = State()
    waiting_part = State()


class VinPhotoStates(StatesGroup):
    waiting_photo = State()
    waiting_part = State()


class PhotoStates(StatesGroup):
    waiting_photo = State()
    waiting_part = State()


class MmyStates(StatesGroup):
    waiting_make = State()
    waiting_model = State()
    waiting_year = State()


async def _notify_admins(bot: Bot, text: str) -> None:
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass


# ---------- entry ----------
@router.callback_query(F.data == "select")
async def cb_select(callback: CallbackQuery):
    await safe_edit(callback.message, "🔍 <b>Подбор запчастей</b>\nВыберите способ:", reply_markup=selection_menu())
    await callback.answer()


# ---------- VIN ----------
@router.callback_query(F.data == "sel:vin")
async def cb_sel_vin(callback: CallbackQuery, state: FSMContext):
    await state.set_state(VinStates.waiting_vin)
    await safe_edit(callback.message, 
        "🔢 Пришлите VIN (17 символов, без I/O/Q):\nПример: <code>XTA21150064234567</code>",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


@router.message(VinStates.waiting_vin)
async def msg_vin(message: Message, state: FSMContext):
    vin = (message.text or "").strip().upper().replace(" ", "")
    if not VIN_RE.match(vin):
        await message.answer("❌ VIN должен быть 17 символов (A–Z, 0–9, без I/O/Q). Попробуйте ещё раз.")
        return
    await state.update_data(vin=vin)
    # Авторасшифровка (бесплатный NHTSA), менеджер — fallback
    await message.answer("⏳ Расшифровываю VIN...")
    decoded = await decode_vin(vin)
    if decoded:
        await state.update_data(decoded=decoded)
        auto = " ".join(x for x in [decoded.get("make"), decoded.get("model"), str(decoded.get("year") or "")] if x)
        await message.answer(f"🚗 Авто по VIN (авто): <b>{html.escape(auto)}</b>\nЕсли неверно — менеджер уточнит вручную.")
    else:
        await state.update_data(decoded=None)
        await message.answer("ℹ️ Авто-расшифровка не удалась — менеджер определит авто вручную.")
    await state.set_state(VinStates.waiting_part)
    await message.answer("Что ищете? (например: передние колодки, радиатор). До 500 символов.")


@router.message(VinStates.waiting_part)
async def msg_vin_part(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    part = (message.text or "").strip()[:500]
    if len(part) < 2:
        await message.answer("Опишите деталь чуть подробнее.")
        return
    decoded = data.get("decoded") or {}
    await state.clear()
    async with SessionFactory() as session:
        session.add(SelectionRequest(
            user_id=message.from_user.id, kind="vin",
            vin=data["vin"], text=part,
            make=decoded.get("make"), model=decoded.get("model"), year=decoded.get("year"),
        ))
        await session.commit()
    auto = " ".join(x for x in [decoded.get("make"), decoded.get("model"), str(decoded.get("year") or "")] if x)
    extra = f"\nАвто: {html.escape(auto)}" if auto else ""
    await message.answer(
        f"✅ Заявка принята!\nVIN: <code>{html.escape(data['vin'])}</code>{extra}\nМенеджер подберёт и ответит сюда.",
        reply_markup=back_to_menu(),
    )
    await _notify_admins(bot, f"🔢 Новая заявка VIN\nuser={message.from_user.id}\nVIN={html.escape(data['vin'])}\nАвто: {html.escape(auto)}\nИщет: {html.escape(part[:200])}")


# ---------- VIN с фото ----------
@router.callback_query(F.data == "sel:vinphoto")
async def cb_sel_vinphoto(callback: CallbackQuery, state: FSMContext):
    await state.set_state(VinPhotoStates.waiting_photo)
    await safe_edit(callback.message, 
        "📷 Пришлите фото VIN-номера (табличка под стеклом, наклейка на стойке, СТС):",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


@router.message(VinPhotoStates.waiting_photo)
async def msg_vinphoto(message: Message, state: FSMContext, bot: Bot):
    if not message.photo:
        await message.answer("Пришлите именно фото.")
        return
    file = await bot.get_file(message.photo[-1].file_id)
    if file.file_size and file.file_size > 5 * 1024 * 1024:
        await message.answer("Фото слишком большое (лимит 5 МБ). Попробуйте другое.")
        return
    await message.answer("⏳ Читаю VIN с фото...")
    buf = io.BytesIO()
    await bot.download_file(file.file_path, buf)
    vin = await extract_vin_from_photo(buf.getvalue())
    if not vin:
        if settings.photo_ai_enabled:
            await message.answer("❌ VIN не распознан — попробуйте чётче или введите вручную.",
                                 reply_markup=selection_menu())
        else:
            await message.answer("ℹ️ Авто-чтение выключено — фото передано менеджеру.",
                                 reply_markup=back_to_menu())
            async with SessionFactory() as session:
                session.add(SelectionRequest(
                    user_id=message.from_user.id, kind="vin_photo",
                    photo_id=message.photo[-1].file_id, text="VIN с фото (ИИ выкл)",
                ))
                await session.commit()
            await _notify_admins(bot, f"📷 VIN с фото (ИИ выкл)\nuser={message.from_user.id}")
        await state.clear()
        return
    await state.update_data(vin=vin)
    await message.answer(f"✅ VIN с фото: <code>{html.escape(vin)}</code>\n⏳ Расшифровываю...")
    decoded = await decode_vin(vin)
    if decoded:
        await state.update_data(decoded=decoded)
        auto = " ".join(x for x in [decoded.get("make"), decoded.get("model"), str(decoded.get("year") or "")] if x)
        await message.answer(f"🚗 Авто (авто): <b>{html.escape(auto)}</b>")
    else:
        await state.update_data(decoded=None)
        await message.answer("ℹ️ Расшифровка не удалась — менеджер определит вручную.")
    await state.set_state(VinPhotoStates.waiting_part)
    await message.answer("Что ищете? (до 500 символов).")


@router.message(VinPhotoStates.waiting_part)
async def msg_vinphoto_part(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    part = (message.text or "").strip()[:500]
    if len(part) < 2:
        await message.answer("Опишите деталь чуть подробнее.")
        return
    decoded = data.get("decoded") or {}
    await state.clear()
    async with SessionFactory() as session:
        session.add(SelectionRequest(
            user_id=message.from_user.id, kind="vin_photo",
            vin=data["vin"], text=part,
            make=decoded.get("make"), model=decoded.get("model"), year=decoded.get("year"),
        ))
        await session.commit()
    await message.answer("✅ Заявка принята! Менеджер подберёт и ответит сюда.", reply_markup=back_to_menu())
    await _notify_admins(bot, f"📷 VIN с фото\nuser={message.from_user.id}\nVIN={html.escape(data['vin'])}\nИщет: {html.escape(part[:200])}")


# ---------- Photo ----------
@router.callback_query(F.data == "sel:photo")
async def cb_sel_photo(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PhotoStates.waiting_photo)
    await safe_edit(callback.message, "📸 Пришлите чёткое фото детали (1 фото):", reply_markup=back_to_menu())
    await callback.answer()


@router.message(PhotoStates.waiting_photo)
async def msg_photo(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Пришлите именно фото, не файл/текст.")
        return
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await state.set_state(PhotoStates.waiting_part)
    await message.answer("Что это / что ищете? Напишите 1–2 фразы (до 500 символов).")


@router.message(PhotoStates.waiting_part)
async def msg_photo_part(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    part = (message.text or "").strip()[:500]
    if len(part) < 2:
        await message.answer("Опишите чуть подробнее.")
        return
    photo_id = data.get("photo_id")
    await state.clear()

    # ИИ-распознавание: скачиваем фото из Telegram (до 5 МБ), отправляем в vision API
    ai_text: str | None = None
    if photo_id:
        try:
            file = await bot.get_file(photo_id)
            if file.file_size and file.file_size > 5 * 1024 * 1024:
                await message.answer("ℹ️ Фото большое — ИИ пропускаю, менеджер посмотрит вручную.")
            else:
                buf = io.BytesIO()
                await bot.download_file(file.file_path, buf)
                ai_text = await recognize_part(buf.getvalue())
        except Exception:
            ai_text = None
    if ai_text:
        await message.answer(f"🤖 <b>Предварительно (ИИ):</b>\n{html.escape(ai_text)}\n\nМенеджер подтвердит и подберёт точный вариант.")
    elif settings.photo_ai_enabled:
        await message.answer("ℹ️ ИИ не смог распознать — менеджер посмотрит вручную.")
    else:
        await message.answer("✅ Фото принято! Менеджер опознает деталь и ответит сюда.", reply_markup=back_to_menu())
        await _notify_admins(bot, f"📸 Новая заявка по фото\nuser={message.from_user.id}\nИщет: {html.escape(part[:200])}")
        async with SessionFactory() as session:
            session.add(SelectionRequest(
                user_id=message.from_user.id, kind="photo",
                photo_id=photo_id, text=part,
            ))
            await session.commit()
        return

    async with SessionFactory() as session:
        session.add(SelectionRequest(
            user_id=message.from_user.id, kind="photo",
            photo_id=photo_id, text=f"{part}\n---\nИИ-гипотеза: {(ai_text or '')[:500]}",
        ))
        await session.commit()
    if ai_text:
        await message.answer("✅ Заявка сохранена.", reply_markup=back_to_menu())
    await _notify_admins(bot, f"📸 Новая заявка по фото\nuser={message.from_user.id}\nИщет: {html.escape(part[:200])}\nИИ: {html.escape((ai_text or '—')[:300])}")


# ---------- Марка / модель / год (с пагинацией под большой справочник) ----------
PER_PAGE = 12


def _page_kb(items: list[tuple[int, str]], page: int, total: int, prefix: str, back_cb: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for _id, name in items:
        b.add(InlineKeyboardButton(text=name, callback_data=f"{prefix}:{_id}"))
    b.adjust(2)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"{prefix}-page:{page-1}"))
    if (page + 1) * PER_PAGE < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"{prefix}-page:{page+1}"))
    if nav:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb))
    return b.as_markup()


async def _send_makes(target: Message | CallbackQuery, state: FSMContext, page: int = 0) -> None:
    async with SessionFactory() as session:
        total = (await session.execute(select(func.count(VehicleMake.id)))).scalar() or 0
        makes = (await session.execute(
            select(VehicleMake).order_by(VehicleMake.name).offset(page * PER_PAGE).limit(PER_PAGE)
        )).scalars().all()
    text = f"🚗 Выберите марку (стр. {page+1}):"
    kb = _page_kb([(m.id, m.name) for m in makes], page, total, "mmy:make", "mmy:back")
    if isinstance(target, CallbackQuery):
        await safe_edit(target.message, text, reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == "mmy:back")
async def cb_mmy_back(callback: CallbackQuery, state: FSMContext):
    """Назад из выбора марки: в каталоге — в меню, в подборе — в меню подбора."""
    from app.handlers.selection import MmyStates  # noqa
    flow = (await state.get_data()).get("flow", "select")
    await state.clear()
    if flow == "catalog":
        from app.keyboards.main import main_menu
        from app.config import settings
        await safe_edit(callback.message, 
            "🚗 Выберите раздел 👇",
            reply_markup=main_menu(settings.is_admin(callback.from_user.id)),
        )
    else:
        await safe_edit(callback.message, "🔍 <b>Подбор запчастей</b>\nВыберите способ:", reply_markup=selection_menu())
    await callback.answer()


@router.callback_query(F.data == "mmy:backmakes")
async def cb_mmy_backmakes(callback: CallbackQuery, state: FSMContext):
    await state.set_state(MmyStates.waiting_make)
    await _send_makes(callback, state, 0)


async def _send_models(callback: CallbackQuery, state: FSMContext, make_id: int, page: int = 0) -> None:
    async with SessionFactory() as session:
        make = await session.get(VehicleMake, make_id)
        if not make:
            await callback.answer("Марка не найдена", show_alert=True)
            return
        total = (await session.execute(
            select(func.count(VehicleModel.id)).where(VehicleModel.make_id == make_id)
        )).scalar() or 0
        models = (await session.execute(
            select(VehicleModel).where(VehicleModel.make_id == make_id)
            .order_by(VehicleModel.name).offset(page * PER_PAGE).limit(PER_PAGE)
        )).scalars().all()
    await state.update_data(make_id=make.id, make_name=make.name)
    text = f"🚗 <b>{html.escape(make.name)}</b> — модель (стр. {page+1}):"
    kb = _page_kb([(m.id, m.name) for m in models], page, total, "mmy:model", "mmy:backmakes")
    await safe_edit(callback.message, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "sel:mmy")
async def cb_sel_mmy(callback: CallbackQuery, state: FSMContext):
    async with SessionFactory() as session:
        total = (await session.execute(select(func.count(VehicleMake.id)))).scalar() or 0
    if not total:
        await safe_edit(callback.message, 
            "🚗 Справочник авто пока пуст — оставьте VIN, подберём вручную.",
            reply_markup=selection_menu(),
        )
        await callback.answer()
        return
    await state.update_data(flow="select")
    await state.set_state(MmyStates.waiting_make)
    await _send_makes(callback, state, 0)


@router.callback_query(F.data.startswith("mmy:make-page:"))
async def cb_mmy_makes_page(callback: CallbackQuery, state: FSMContext):
    await _send_makes(callback, state, int(callback.data.split(":")[2]))


@router.callback_query(F.data.startswith("mmy:make:"))
async def cb_mmy_make(callback: CallbackQuery, state: FSMContext):
    await state.set_state(MmyStates.waiting_model)
    await _send_models(callback, state, int(callback.data.split(":")[2]), 0)


@router.callback_query(F.data.startswith("mmy:model-page:"))
async def cb_mmy_models_page(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    make_id = data.get("make_id")
    if not make_id:
        await callback.answer("Выберите марку заново", show_alert=True)
        return
    await _send_models(callback, state, make_id, int(callback.data.split(":")[2]))


@router.callback_query(F.data.startswith("mmy:model:"))
async def cb_mmy_model(callback: CallbackQuery, state: FSMContext):
    model_id = int(callback.data.split(":")[2])
    async with SessionFactory() as session:
        model = await session.get(VehicleModel, model_id)
    if not model:
        await callback.answer("Не найдено", show_alert=True)
        return
    await state.update_data(model_id=model.id, model_name=model.name)
    await state.set_state(MmyStates.waiting_year)
    await safe_edit(callback.message, 
        "📅 Введите год выпуска (1990–{}):".format(datetime.now().year + 1),
        reply_markup=back_to_menu(),
    )
    await callback.answer()


@router.message(MmyStates.waiting_year)
async def msg_mmy_year(message: Message, state: FSMContext, bot: Bot):
    year_txt = (message.text or "").strip()
    now_year = datetime.now().year + 1
    if not year_txt.isdigit() or not 1990 <= int(year_txt) <= now_year:
        await message.answer(f"Введите год 1990–{now_year}.")
        return
    year = int(year_txt)
    data = await state.get_data()
    flow = data.get("flow", "select")

    # Ветка каталога: запоминаем авто и показываем категории
    if flow == "catalog":
        await state.update_data(car={
            "make_id": data["make_id"], "model_id": data["model_id"], "year": year,
            "make_name": data.get("make_name", ""), "model_name": data.get("model_name", ""),
        })
        await state.set_state(None)
        from app.handlers.catalog import send_categories
        await send_categories(message, state)
        return

    await state.clear()

    # Ищем подходящие товары через fitments
    async with SessionFactory() as session:
        stmt = (
            select(Product)
            .join(Fitment, Fitment.product_id == Product.id)
            .where(
                Product.is_active == True,  # noqa: E712
                Fitment.make_id == data["make_id"],
                Fitment.model_id == data["model_id"],
                (Fitment.year_from.is_(None) | (Fitment.year_from <= year)),
                (Fitment.year_to.is_(None) | (Fitment.year_to >= year)),
            ).limit(10)
        )
        rows = (await session.execute(stmt)).scalars().all()
        session.add(SelectionRequest(
            user_id=message.from_user.id, kind="mmy",
            make=data.get("make_name"), model=data.get("model_name"),
            year=year, text=f"Подбор {html.escape(str(data.get('make_name') or ''))} {html.escape(str(data.get('model_name') or ''))} {year}",
        ))
        await session.commit()

    if not rows:
        await message.answer(
            f"🚗 {html.escape(data.get('make_name',''))} {html.escape(data.get('model_name',''))} {year}: "
            "точно подходящих позиций не нашли — менеджер подберёт вручную.",
            reply_markup=back_to_menu(),
        )
        await _notify_admins(bot, f"🚗 Заявка ММГ без совпадений\nuser={message.from_user.id}\n{html.escape(str(data.get('make_name') or ''))} {html.escape(str(data.get('model_name') or ''))} {year}")
        return
    b = InlineKeyboardBuilder()
    for p in rows:
        b.add(InlineKeyboardButton(text=f"{p.name} — {p.price} ₽", callback_data=f"prod:{p.id}"))
    b.add(InlineKeyboardButton(text="🏠 В меню", callback_data="menu"))
    b.adjust(1)
    await message.answer(f"✅ Найдено для {html.escape(str(data.get('make_name') or ''))} {html.escape(str(data.get('model_name') or ''))} {year}:", reply_markup=b.as_markup())
    await _notify_admins(bot, f"🚗 Подбор ММГ\nuser={message.from_user.id}\n{html.escape(str(data.get('make_name') or ''))} {html.escape(str(data.get('model_name') or ''))} {year}\nНайдено товаров: {len(rows)}")
