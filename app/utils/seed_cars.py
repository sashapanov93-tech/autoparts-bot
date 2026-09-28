"""Заполнение справочника марок/моделей.

Источники:
1. NHTSA vPIC (бесплатно, без ключа) — модели для мировых марок.
2. Встроенный список — марки/мой рынок, которых нет у NHTSA
   (Lada, UAZ, китайские бренды и т.п.).

Запуск:  uv run python -m app.utils.seed_cars
Идемпотентно: существующие записи пропускаются.
"""

import asyncio
import logging

import httpx
from sqlalchemy import func, select

from app.db.base import SessionFactory, init_db
from app.db.models import VehicleMake, VehicleModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("seed_cars")

# Марки, модели которых тянем из NHTSA
NHTSA_MAKES = [
    "Toyota", "Kia", "Hyundai", "Nissan", "Honda", "Mazda", "Mitsubishi",
    "Suzuki", "Subaru", "Lexus", "Infiniti", "Acura", "BMW", "Mercedes-Benz",
    "Audi", "Volkswagen", "Skoda", "Opel", "Peugeot", "Renault", "Citroen",
    "Fiat", "Volvo", "Ford", "Chevrolet", "Jeep", "Dodge", "Chrysler",
    "Cadillac", "Tesla", "Land Rover", "Jaguar", "Mini", "Porsche",
    "Seat", "Dacia", "SsangYong", "Daewoo", "Isuzu", "Daihatsu", "Smart",
    "Alfa Romeo", "Genesis", "Aston Martin", "Bentley", "Cadillac", "Lincoln",
    "Chrysler", "Ram",
]

# Марки + модели вручную (нет у NHTSA или мусор вместо них)
CURATED: dict[str, list[str]] = {
    "Lada": ["Granta", "Vesta", "Niva Legend", "Niva Travel", "Largus", "Xray",
             "Priora", "Kalina", "2110", "2112", "2114", "2115", "2107", "2109", "Oka"],
    "UAZ": ["Patriot", "Hunter", "Pickup", "Profi", "452 Bukhanka"],
    "GAZ": ["Gazelle Next", "Gazelle Business", "Sobol", "Volga 3110", "Siber"],
    "Moskvich": ["3", "3e", "6"],
    "ZAZ": ["Chance", "Lanos", "Sens", "Slavuta", "Tavria"],
    "Chery": ["Tiggo 4", "Tiggo 7 Pro", "Tiggo 8 Pro", "Arrizo 8", "Amulet",
              "Bonus", "Very", "M11", "Tiggo T11", "Fora", "Kimo"],
    "Geely": ["Coolray", "Atlas", "Atlas Pro", "Emgrand", "Monjaro", "Tugella", "Okavango"],
    "Haval": ["Jolion", "F7", "F7x", "H9", "Dargo", "M6", "H6"],
    "Changan": ["CS35", "CS55", "CS75", "Uni-K", "Uni-V", "Eado", "Alsvin"],
    "Exeed": ["TXL", "VX", "LX", "RX"],
    "Omoda": ["C5", "S5"],
    "Jaecoo": ["J7", "J8"],
    "Jetour": ["Dashing", "X70", "X90", "T2"],
    "Great Wall": ["Hover H3", "Hover H5", "Wingle 7", "Poer"],
    "Tank": ["300", "500"],
    "Lifan": ["X60", "X50", "Solano", "Smily", "Murman", "Cebrium"],
    "BYD": ["Song Plus", "Tang", "Han", "Dolphin", "Atto 3", "F3"],
    "FAW": ["Bestune T77", "Bestune B70", "Vita", "Oley", "Besturn X80"],
    "Dongfeng": ["AX7", "580", "Shine Max"],
    "JAC": ["J7", "JS4", "JS6", "T8"],
    "BAIC": ["X35", "X55", "BJ40"],
    "Hongqi": ["H5", "HS5", "E-HS9"],
    "Voyah": ["Free", "Dream"],
    "Zeekr": ["001", "X", "007"],
    "Li Auto": ["L7", "L8", "L9", "One"],
    "Kaiyi": ["E5", "X3", "X7"],
    "Belgee": ["X50", "X70"],
    "Ravon": ["R2", "R3 Nexia", "R4"],
    "Sollers": ["Atlant", "Argo", "ST6"],
    "Evolute": ["i-Pro", "i-Joy", "i-Sky"],
    "Foton": ["Tunland", "Sauvana", "Toano"],
    "SWM": ["G01", "G05"],
    "Avatr": ["11", "12"],
    "Skoda": ["Octavia", "Rapid", "Kodiaq", "Superb", "Fabia", "Yeti", "Karoq",
              "Kamiq", "Enyaq", "Scala"],
    "Dacia": ["Logan", "Sandero", "Duster", "Jogger", "Spring", "Dokker", "Lodgy", "Bigster"],
    "SsangYong": ["Actyon", "Kyron", "Rexton", "Tivoli", "Korando", "Musso", "Torres"],
}


def _make_match(got: str, want: str) -> bool:
    g, w = got.strip().lower(), want.strip().lower()
    return g == w or g.startswith(w)


async def fetch_nhtsa_models(client: httpx.AsyncClient, make: str) -> list[str]:
    try:
        r = await client.get(
            f"https://vpic.nhtsa.dot.gov/api/vehicles/GetModelsForMake/{make}?format=json",
            timeout=20.0,
        )
        r.raise_for_status()
        results = r.json().get("Results") or []
    except Exception as e:
        logger.warning("%s: fetch failed: %s", make, type(e).__name__)
        return []
    # Отсекаем чужой мусор (как Pulada вместо Lada)
    good = [x for x in results if _make_match(str(x.get("Make_Name", "")), make)]
    if not good:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for x in good:
        name = str(x.get("Model_Name", "")).strip()[:80]
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return out[:120]


async def main() -> None:
    await init_db()
    sem = asyncio.Semaphore(5)
    async with httpx.AsyncClient() as client:
        async def one(make: str) -> tuple[str, list[str]]:
            async with sem:
                await asyncio.sleep(0.2)
                return make, await fetch_nhtsa_models(client, make)

        fetched = await asyncio.gather(*(one(m) for m in NHTSA_MAKES))

    async with SessionFactory() as s:
        n_makes = n_models = 0
        # 1. NHTSA-марки
        for make, models in fetched:
            mk = (await s.execute(
                select(VehicleMake).where(func.lower(VehicleMake.name) == make.lower())
            )).scalar_one_or_none()
            if not mk:
                mk = VehicleMake(name=make)
                s.add(mk)
                await s.flush()
                n_makes += 1
            existing = {
                r.lower() for r in (await s.execute(
                    select(VehicleModel.name).where(VehicleModel.make_id == mk.id)
                )).scalars().all()
            }
            for m in models:
                if m.lower() not in existing:
                    s.add(VehicleModel(make_id=mk.id, name=m))
                    existing.add(m.lower())
                    n_models += 1
            if not models:
                logger.warning("%s: NHTSA пусто, только марка", make)
        # 2. Ручной список
        for make, models in CURATED.items():
            mk = (await s.execute(
                select(VehicleMake).where(func.lower(VehicleMake.name) == make.lower())
            )).scalar_one_or_none()
            if not mk:
                mk = VehicleMake(name=make)
                s.add(mk)
                await s.flush()
                n_makes += 1
            existing = {
                r.lower() for r in (await s.execute(
                    select(VehicleModel.name).where(VehicleModel.make_id == mk.id)
                )).scalars().all()
            }
            for m in models:
                if m.lower() not in existing:
                    s.add(VehicleModel(make_id=mk.id, name=m))
                    n_models += 1
        await s.commit()
    logger.info("DONE: +makes=%d +models=%d", n_makes, n_models)


if __name__ == "__main__":
    asyncio.run(main())
