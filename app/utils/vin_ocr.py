"""Извлечение VIN с фото (табличка/наклейка) через vision-ИИ.

Без PHOTO_AI_API_KEY — вернуть None, заявка уйдёт менеджеру вручную.
"""

import logging
import re

import httpx

from app.config import settings
from app.utils.photo_ai import MAX_BYTES

logger = logging.getLogger(__name__)

VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")

PROMPT = (
    "На фото — VIN-номер автомобиля (табличка, наклейка, документы). "
    "Верни ТОЛЬКО сам VIN: 17 символов, латиница и цифры без I, O, Q. "
    "Никаких пояснений, пробелов и форматирования. "
    "Если VIN на фото нет или он нечитаем — верни слово NONE."
)


async def extract_vin_from_photo(photo_bytes: bytes) -> str | None:
    """Вернуть VIN строкой или None."""
    import base64

    if not settings.photo_ai_enabled:
        return None
    if not photo_bytes or len(photo_bytes) > MAX_BYTES:
        return None
    b64 = base64.b64encode(photo_bytes).decode()
    url = f"{settings.PHOTO_AI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.PHOTO_AI_API_KEY}"}
    payload = {
        "model": settings.PHOTO_AI_MODEL,
        "max_tokens": 100,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip().upper()
    except Exception as e:
        logger.warning("VIN OCR failed: %s", type(e).__name__)
        return None
    m = VIN_RE.search(text.replace(" ", ""))
    return m.group(0) if m else None
