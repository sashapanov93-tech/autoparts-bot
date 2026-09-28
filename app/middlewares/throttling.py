from time import monotonic
from collections import defaultdict
from typing import Any, Awaitable, Callable, Union

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message


class ThrottlingMiddleware(BaseMiddleware):
    """Антифлуд для сообщений И кнопок: не чаще 1 события в `rate` сек с пользователя."""

    def __init__(self, rate: float = 0.7):
        self.rate = rate
        self._last: dict[int, float] = defaultdict(float)

    async def __call__(
        self,
        handler: Callable[[Union[Message, CallbackQuery], dict[str, Any]], Awaitable[Any]],
        event: Union[Message, CallbackQuery],
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        user_id = user.id if user else 0
        now = monotonic()
        if now - self._last[user_id] < self.rate:
            # Кнопки: гасим спиннер, сообщения: молча игнор
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer()
                except Exception:
                    pass
            return None
        self._last[user_id] = now
        return await handler(event, data)
