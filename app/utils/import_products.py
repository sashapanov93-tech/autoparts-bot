"""Импорт каталога товаров из таблицы (CSV / XLSX).

Формат колонок (первая строка — заголовки):
  article | name | price | stock | category | description | make | model | year_from | year_to

Обязательные: article, name, price.
Необязательные: stock (=0), category (создастся), description,
make+model (+годы) — создастся применимость (fitment).
По существующему article — обновление (upsert).
Лимиты: файл до 5 МБ, до 2000 строк.
"""

import csv
import io

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 2000

HEADERS = ["article", "name", "price", "stock", "category",
           "description", "make", "model", "year_from", "year_to"]


def parse_file(data: bytes, filename: str) -> tuple[list[dict], list[str]]:
    """Вернуть (строки, ошибки). Строки — dict по HEADERS, значения строками."""
    errors: list[str] = []
    if not data or len(data) > MAX_BYTES:
        return [], ["Файл пустой или больше 5 МБ"]
    name = filename.lower()
    rows: list[dict] = []
    try:
        if name.endswith(".csv"):
            text = data.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            raw = list(reader)
        elif name.endswith((".xlsx", ".xlsm")):
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb.active
            it = ws.iter_rows(values_only=True)
            header = [(str(c).strip().lower() if c is not None else "") for c in next(it)]
            raw = [dict(zip(header, r)) for r in it]
        else:
            return [], ["Нужен .csv или .xlsx"]
    except Exception as e:
        return [], [f"Не смог прочитать файл: {type(e).__name__}"]
    if len(raw) > MAX_ROWS:
        return [], [f"Слишком много строк: {len(raw)} (лимит {MAX_ROWS})"]
    for i, r in enumerate(raw, start=2):
        row = {h: str(r.get(h, "") or "").strip() for h in HEADERS}
        if not row["article"] and not row["name"]:
            continue  # пустая строка
        if not row["article"]:
            errors.append(f"Строка {i}: нет артикула")
            continue
        if not row["name"]:
            errors.append(f"Строка {i}: нет названия")
            continue
        try:
            price = float(row["price"].replace(",", "."))
        except ValueError:
            errors.append(f"Строка {i}: плохая цена «{row['price'][:20]}»")
            continue
        if not 0 < price < 100_000_000:
            errors.append(f"Строка {i}: нереальная цена")
            continue
        row["price"] = price  # type: ignore
        stock = row["stock"]
        if stock and (not stock.isdigit() or not 0 <= int(stock) <= 100_000):
            errors.append(f"Строка {i}: плохой остаток")
            continue
        row["stock"] = int(stock) if stock else 0  # type: ignore
        for y in ("year_from", "year_to"):
            if row[y] and (not row[y].isdigit() or not 1950 <= int(row[y]) <= 2100):
                errors.append(f"Строка {i}: плохой год {y}")
                break
        else:
            rows.append(row)
    return rows, errors


async def apply_rows(rows: list[dict]) -> dict:
    """Upsert товаров (+категории, +применимость). Вернуть статистику."""
    from sqlalchemy import select

    from app.db.base import SessionFactory
    from app.db.models import Category, Fitment, Product, VehicleMake, VehicleModel

    added = updated = fitments = 0
    async with SessionFactory() as s:
        # Карты для регистронезависимого поиска (SQLite lower() не дружит с кириллицей)
        cats = {c.name.lower(): c for c in (await s.execute(select(Category))).scalars().all()}
        makes = {m.name.lower(): m for m in (await s.execute(select(VehicleMake))).scalars().all()}
        models: dict[tuple[int, str], VehicleModel] = {}
        for md in (await s.execute(select(VehicleModel))).scalars().all():
            models[(md.make_id, md.name.lower())] = md

        for row in rows:
            art = row["article"][:64]
            prod = (await s.execute(select(Product).where(Product.article == art))).scalar_one_or_none()
            cat_id = None
            if row["category"]:
                cname = row["category"][:100]
                cat = cats.get(cname.lower())
                if not cat:
                    cat = Category(name=cname)
                    s.add(cat)
                    await s.flush()
                    cats[cname.lower()] = cat
                cat_id = cat.id
            if prod:
                prod.name = row["name"][:200]
                prod.price = row["price"]
                prod.stock = row["stock"]
                if cat_id:
                    prod.category_id = cat_id
                if row["description"]:
                    prod.description = row["description"][:1000]
                updated += 1
            else:
                prod = Product(
                    article=art, name=row["name"][:200], price=row["price"],
                    stock=row["stock"], category_id=cat_id,
                    description=row["description"][:1000] or None,
                )
                s.add(prod)
                await s.flush()
                added += 1
            # Применимость make+model
            if row["make"] and row["model"]:
                mk = makes.get(row["make"].lower())
                if not mk:
                    mk = VehicleMake(name=row["make"][:80])
                    s.add(mk)
                    await s.flush()
                    makes[row["make"].lower()] = mk
                md = models.get((mk.id, row["model"].lower()))
                if not md:
                    md = VehicleModel(make_id=mk.id, name=row["model"][:80])
                    s.add(md)
                    await s.flush()
                    models[(mk.id, row["model"].lower())] = md
                yf = int(row["year_from"]) if row["year_from"] else None
                yt = int(row["year_to"]) if row["year_to"] else None
                exists = (await s.execute(select(Fitment).where(
                    Fitment.product_id == prod.id, Fitment.make_id == mk.id,
                    Fitment.model_id == md.id))).scalar_one_or_none()
                if not exists:
                    s.add(Fitment(product_id=prod.id, make_id=mk.id,
                                  model_id=md.id, year_from=yf, year_to=yt))
                    fitments += 1
        await s.commit()
    return {"added": added, "updated": updated, "fitments": fitments}
