"""Веб-админка: один админ (Basic Auth из .env). Товары, категории, применимость, заявки, заказы."""

import html as _html
import secrets
import time
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import func, select

from app.config import settings
from app.db.base import SessionFactory, init_db
from app.db.models import (
    Category, Fitment, Order, Product, SelectionRequest, VehicleMake, VehicleModel,
)

app = FastAPI(title="Autoparts admin", docs_url=None, redoc_url=None)
security = HTTPBasic()

# --- Антибрутфорс: IP -> [неудачи, бан_до] ---
_auth_failures: dict[str, list] = {}
MAX_AUTH_TRIES = 10
AUTH_BAN_SEC = 300


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "?")[:64]


def check_auth(request: Request, credentials: HTTPBasicCredentials = Depends(security)) -> str:
    ip = _client_ip(request)
    fails, banned_until = _auth_failures.get(ip, [0, 0])
    if time.time() < banned_until:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток. Подождите 5 минут.")
    ok_user = secrets.compare_digest(credentials.username, settings.WEB_ADMIN_USER)
    ok_pass = secrets.compare_digest(credentials.password, settings.WEB_ADMIN_PASSWORD)
    if not (ok_user and ok_pass):
        fails += 1
        _auth_failures[ip] = [fails, time.time() + AUTH_BAN_SEC if fails >= MAX_AUTH_TRIES else 0]
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нет доступа",
                            headers={"WWW-Authenticate": "Basic"})
    _auth_failures.pop(ip, None)
    return credentials.username


def verify_origin(request: Request) -> None:
    """CSRF-защита POST-форм: требуем Origin/Referer с нашего хоста."""
    origin = request.headers.get("origin") or ""
    referer = request.headers.get("referer") or ""
    if not origin and not referer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет Origin/Referer")
    allowed = {request.url.hostname or ""}
    try:
        allowed.add(urlparse(settings.WEB_PUBLIC_URL).hostname or "")
    except Exception:
        pass
    for raw in (origin, referer):
        try:
            host = urlparse(raw).hostname or ""
        except Exception:
            continue
        if host and host in allowed:
            return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Чужой Origin")


PAGE = """<html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:sans-serif;max-width:900px;margin:20px auto;padding:0 12px}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:6px;font-size:14px}}
nav a{{margin-right:12px}}</style></head><body>
<nav><a href="/">Главная</a><a href="/products">Товары</a><a href="/selection">Заявки</a>
<a href="/orders">Заказы</a><a href="/cars">Авто</a></nav><h2>{title}</h2>{body}</body></html>"""


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(PAGE.format(title=title, body=body))


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    if request.method == "POST":
        try:
            verify_origin(request)
        except HTTPException as e:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": e.detail}, status_code=e.status_code)
    return await call_next(request)


@app.on_event("startup")
async def _startup():
    await init_db()


@app.get("/", response_class=HTMLResponse)
async def index(_: str = Depends(check_auth)):
    async with SessionFactory() as s:
        n_prod = (await s.execute(select(func.count(Product.id)))).scalar()
        n_sel = (await s.execute(select(func.count(SelectionRequest.id)).where(SelectionRequest.status == "new"))).scalar()
        n_ord = (await s.execute(select(func.count(Order.id)).where(Order.status == "new"))).scalar()
    return page("Админка", f"<p>Товаров: {n_prod} · Новых заявок: {n_sel} · Новых заказов: {n_ord}</p>"
                "<p>Товары и заявки — в разделах выше. Пароль меняется в .env (WEB_ADMIN_PASSWORD).</p>")


# ---------- Товары ----------
@app.get("/products", response_class=HTMLResponse)
async def products_list(_: str = Depends(check_auth)):
    async with SessionFactory() as s:
        rows = (await s.execute(select(Product).order_by(Product.id.desc()).limit(100))).scalars().all()
        cats = (await s.execute(select(Category).order_by(Category.name))).scalars().all()
    cat_opts = "".join(f"<option value='{c.id}'>{_html.escape(c.name or '')}</option>" for c in cats)
    trs = "".join(f"<tr><td>{p.id}</td><td>{_html.escape(p.article or '')}</td>"
                   f"<td>{_html.escape(p.name or '')}</td><td>{p.price}</td><td>{p.stock}</td></tr>" for p in rows)
    form = (f"<h3>Добавить товар</h3><form method='post' action='/products'>"
            f"Артикул <input name='article' required maxlength=64> Название <input name='name' required maxlength=200><br>"
            f"Цена <input name='price' required> Остаток <input name='stock' value='0'><br>"
            f"Категория <select name='category_id'><option value=''>—</option>{cat_opts}</select> "
            f"<button>Добавить</button></form>"
            "<h3>Категория</h3><form method='post' action='/categories'>"
            "Название <input name='name' required maxlength=100> <button>Создать</button></form>"
            "<h3>Импорт таблицей</h3><p><a href='/products/template'>Скачать шаблон CSV</a></p>"
            "<form method='post' action='/products/import' enctype='multipart/form-data'>"
            "<input type='file' name='file' accept='.csv,.xlsx,.xlsm' required> "
            "<button>Загрузить</button></form>"
            "<p><small>Колонки: article, name, price, stock, category, description, make, model, year_from, year_to. "
            "По существующему артикулу — обновление.</small></p>")
    return page("Товары", form + f"<table><tr><th>ID</th><th>Артикул</th><th>Название</th><th>Цена</th><th>Ост.</th></tr>{trs}</table>")


@app.post("/products")
async def products_add(article: str = Form(max_length=64), name: str = Form(max_length=200),
                       price: float = Form(), stock: int = Form(0),
                       category_id: str = Form(""), _: str = Depends(check_auth)):
    if not 0 < price < 100_000_000 or not 0 <= stock <= 100_000:
        raise HTTPException(400, "Некорректная цена/остаток")
    async with SessionFactory() as s:
        exists = (await s.execute(select(Product).where(Product.article == article.strip()))).scalar_one_or_none()
        if exists:
            raise HTTPException(400, "Такой артикул уже есть")
        cid = int(category_id) if category_id.isdigit() else None
        s.add(Product(article=article.strip(), name=name.strip(), price=price, stock=stock, category_id=cid))
        await s.commit()
    return RedirectResponse("/products", status_code=303)


@app.get("/products/template")
async def products_template(_: str = Depends(check_auth)):
    from fastapi.responses import PlainTextResponse

    from app.utils.import_products import HEADERS
    sample = (
        ",".join(HEADERS) + "\n"
        "CT-1234,Колодки передние Toyota Camry,2499,10,Тормоза,Керамические,Toyota,Camry,2018,2024\n"
        "FL-007,Фильтр масляный,499,50,Фильтры,,,\n"
    )
    return PlainTextResponse(sample, media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=template.csv"})


@app.post("/products/import", response_class=HTMLResponse)
async def products_import(request: Request, _: str = Depends(check_auth)):
    from app.utils.import_products import apply_rows, parse_file

    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(400, "Приложите файл")
    data = await upload.read()  # type: ignore
    rows, errors = parse_file(data, getattr(upload, "filename", "") or "file.csv")
    stats = await apply_rows(rows) if rows else {"added": 0, "updated": 0, "fitments": 0}
    body = (f"<p>✅ Добавлено: {stats['added']} · Обновлено: {stats['updated']} "
            f"· Применимостей: {stats['fitments']}</p>")
    if errors:
        body += "<p>⚠️ Ошибки (первые 30):</p><ul>" + "".join(
            f"<li>{e}</li>" for e in errors[:30]) + "</ul>"
    body += "<p><a href='/products'>← Назад к товарам</a></p>"
    return page("Импорт завершён", body)


@app.post("/categories")
async def categories_add(name: str = Form(max_length=100), _: str = Depends(check_auth)):
    name = name.strip()
    if len(name) < 2:
        raise HTTPException(400, "Короткое название")
    async with SessionFactory() as s:
        exists = (await s.execute(select(Category).where(Category.name == name))).scalar_one_or_none()
        if not exists:
            s.add(Category(name=name))
            await s.commit()
    return RedirectResponse("/products", status_code=303)


# ---------- Авто (марки/модели/применимость) ----------
@app.get("/cars", response_class=HTMLResponse)
async def cars_list(_: str = Depends(check_auth)):
    async with SessionFactory() as s:
        makes = (await s.execute(select(VehicleMake).order_by(VehicleMake.name))).scalars().all()
        models = (await s.execute(select(VehicleModel).order_by(VehicleModel.id.desc()).limit(100))).scalars().all()
        fits = (await s.execute(select(Fitment).order_by(Fitment.id.desc()).limit(100))).scalars().all()
    make_opts = "".join(f"<option value='{m.id}'>{_html.escape(m.name or '')}</option>" for m in makes)
    body = (f"<h3>Марка</h3><form method='post' action='/makes'>Название <input name='name' required maxlength=80> <button>Добавить</button></form>"
            f"<h3>Модель</h3><form method='post' action='/models'>Марка <select name='make_id'>{make_opts}</select> "
            f"Название <input name='name' required maxlength=80> <button>Добавить</button></form>"
            f"<h3>Применимость (товар→авто)</h3><form method='post' action='/fitments'>"
            f"Product ID <input name='product_id' required> Model ID <input name='model_id' required> "
            f"Год от <input name='year_from' placeholder='—'> до <input name='year_to' placeholder='—'> <button>Связать</button></form>"
            f"<p>Моделей: {len(models)}, связей: {len(fits)}</p>")
    return page("Авто и применимость", body)


@app.post("/makes")
async def makes_add(name: str = Form(max_length=80), _: str = Depends(check_auth)):
    name = name.strip()
    async with SessionFactory() as s:
        exists = (await s.execute(select(VehicleMake).where(VehicleMake.name == name))).scalar_one_or_none()
        if not exists and len(name) >= 2:
            s.add(VehicleMake(name=name))
            await s.commit()
    return RedirectResponse("/cars", status_code=303)


@app.post("/models")
async def models_add(make_id: int = Form(), name: str = Form(max_length=80), _: str = Depends(check_auth)):
    async with SessionFactory() as s:
        make = await s.get(VehicleMake, make_id)
        if make and len(name.strip()) >= 1:
            s.add(VehicleModel(make_id=make.id, name=name.strip()))
            await s.commit()
    return RedirectResponse("/cars", status_code=303)


@app.post("/fitments")
async def fitments_add(product_id: int = Form(), model_id: int = Form(),
                       year_from: str = Form(""), year_to: str = Form(""),
                       _: str = Depends(check_auth)):
    yf = int(year_from) if year_from.isdigit() else None
    yt = int(year_to) if year_to.isdigit() else None
    async with SessionFactory() as s:
        p = await s.get(Product, product_id)
        m = await s.get(VehicleModel, model_id)
        if not p or not m:
            raise HTTPException(400, "Товар или модель не найдены")
        s.add(Fitment(product_id=p.id, make_id=m.make_id, model_id=m.id, year_from=yf, year_to=yt))
        await s.commit()
    return RedirectResponse("/cars", status_code=303)


# ---------- Заявки ----------
@app.get("/selection", response_class=HTMLResponse)
async def selection_list(_: str = Depends(check_auth)):
    async with SessionFactory() as s:
        rows = (await s.execute(select(SelectionRequest).order_by(SelectionRequest.id.desc()).limit(100))).scalars().all()
    trs = ""
    for r in rows:
        info = (f"{_html.escape(r.kind or '')} vin={_html.escape(r.vin or '')} "
                f"{_html.escape(r.make or '')} {_html.escape(r.model or '')} {r.year or ''} "
                f"{_html.escape((r.text or '')[:120])}")
        trs += (f"<tr><td>{r.id}</td><td>{r.user_id}</td><td>{info}</td><td>{r.status}</td>"
                f"<td><form method='post' action='/selection/{r.id}/answer'>"
                f"<input name='answer' placeholder='ответ' maxlength=1000><button>Ответить</button></form></td></tr>")
    return page("Заявки на подбор", f"<table><tr><th>ID</th><th>User</th><th>Заявка</th><th>Статус</th><th></th></tr>{trs}</table>")


@app.post("/selection/{req_id}/answer")
async def selection_answer(req_id: int, answer: str = Form(max_length=1000), _: str = Depends(check_auth)):
    from aiogram import Bot
    async with SessionFactory() as s:
        r = await s.get(SelectionRequest, req_id)
        if not r:
            raise HTTPException(404, "Нет заявки")
        r.answer = answer.strip()
        r.status = "answered"
        await s.commit()
        user_id, text = r.user_id, answer.strip()
    # Пытаемся уведомить пользователя через каталог-бота (токен 1-го бота)
    token = settings.catalog_token
    if token and ":" in token:
        try:
            bot = Bot(token=token)
            await bot.send_message(user_id, f"✅ Ответ по подбору #{req_id}:\n{text[:900]}")
            await bot.session.close()
        except Exception:
            pass
    return RedirectResponse("/selection", status_code=303)


# ---------- Заказы ----------
@app.get("/orders", response_class=HTMLResponse)
async def orders_list(_: str = Depends(check_auth)):
    import html as _html

    from app.db.models import OrderItem, Product
    async with SessionFactory() as s:
        rows = (await s.execute(select(Order).order_by(Order.id.desc()).limit(100))).scalars().all()
        oids = [o.id for o in rows]
        items_by_order: dict[int, list[str]] = {}
        if oids:
            q = (select(OrderItem, Product).join(Product, Product.id == OrderItem.product_id)
                 .where(OrderItem.order_id.in_(oids)))
            for oi, p in (await s.execute(q)).all():
                items_by_order.setdefault(oi.order_id, []).append(
                    f"{_html.escape(p.article)} | {_html.escape(p.name)} × {oi.qty}")
    trs = ""
    for o in rows:
        items = "<br>".join(items_by_order.get(o.id, ["—"]))
        trs += (
            f"<tr><td>{o.id}</td><td>{o.user_id}</td><td>{float(o.total):.0f}</td>"
            f"<td>{items}</td><td>{o.status}</td><td>{_html.escape(o.contact or '')}</td>"
            f"<td><form method='post' action='/orders/{o.id}/status'>"
            f"<select name='status'><option>new</option><option>processing</option><option>done</option><option>cancelled</option></select>"
            f"<button>OK</button></form></td></tr>")
    return page("Заказы", f"<table><tr><th>ID</th><th>User</th><th>Сумма</th><th>Состав</th><th>Статус</th><th>Контакт</th><th></th></tr>{trs}</table>")


@app.post("/orders/{order_id}/status")
async def orders_status(order_id: int, status: str = Form(max_length=16), _: str = Depends(check_auth)):
    if status not in ("new", "processing", "done", "cancelled"):
        raise HTTPException(400, "Плохой статус")
    async with SessionFactory() as s:
        o = await s.get(Order, order_id)
        if not o:
            raise HTTPException(404, "Нет заказа")
        o.status = status
        await s.commit()
    return RedirectResponse("/orders", status_code=303)


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"ok": True}
