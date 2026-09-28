"""Распознавание детали по фото через ИИ (OpenAI-совместимый vision API).

- Если PHOTO_AI_API_KEY пуст — вернуть None, заказ уходит менеджеру вручную.
- Лимиты безопасности: JPEG/PNG до 5 МБ, таймаут 30 сек, ключ не логируется.
"""

import base64
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PROMPT = (
    "Ты — эксперт по автозапчастям. По фото определи деталь: "
    "1) название детали на русском, 2) возможная категория (тормоза/подвеска/двигатель/электрика/кузов/...), "
    "3) на что обратить внимание при подборе (маркировка, размеры, сторона). "
    "Если на фото не автодеталь — так и скажи. Ответ короткий, до 600 символов, на русском."
)

MAX_BYTES = 5 * 1024 * 1024


async def recognize_part(photo_bytes: bytes) -> str | None:
    """Вернуть текст-версию ИИ или None (нет ключа / ошибка / не деталь)."""
    if not settings.photo_ai_enabled:
        return None
    if not photo_bytes or len(photo_bytes) > MAX_BYTES:
        return None
    b64 = base64.b64encode(photo_bytes).decode()
    url = f"{settings.PHOTO_AI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.PHOTO_AI_API_KEY}"}
    payload = {
        "model": settings.PHOTO_AI_MODEL,
        "max_tokens": 400,
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
            data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        return text[:1000] if text else None
    except Exception as e:
        logger.warning("Photo AI failed: %s", type(e).__name__)
        return None
