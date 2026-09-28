"""Авторасшифровка VIN через бесплатный NHTSA vPIC (без ключа).

Docs: https://vpic.nhtsa.dot.gov/api/
GET {NHTSA_URL}/{vin}?format=json -> Results[] с полями Make/Model/ModelYear.
Возвращает dict(make, model, year) или None при неудаче. Менеджер — fallback.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _pick(results: list[dict], *names: str) -> str:
    for row in results:
        var = str(row.get("Variable") or "")
        if var in names:
            val = str(row.get("Value") or "").strip()
            if val and val.lower() not in ("not applicable", "not specified"):
                return val[:80]
    return ""


async def decode_vin(vin: str) -> dict | None:
    """Вернуть {'make','model','year'} или None. Никогда не бросает исключение."""
    if not settings.VIN_DECODE_ENABLED:
        return None
    vin = vin.strip().upper()
    if len(vin) != 17:
        return None
    url = f"{settings.NHTSA_URL.rstrip('/')}/{vin}?format=json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("VIN decode failed for %s: %s", vin[:6] + "***", e)
        return None
    try:
        results = data.get("Results") or []
        make = _pick(results, "Make")
        model = _pick(results, "Model")
        year_txt = _pick(results, "Model Year")
        year = int(year_txt) if year_txt.isdigit() else None
        if not (make or model or year):
            return None
        return {"make": make or None, "model": model or None, "year": year}
    except Exception as e:
        logger.warning("VIN parse failed: %s", e)
        return None
