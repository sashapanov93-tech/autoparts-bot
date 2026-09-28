"""Безопасное редактирование сообщений: игнор 'message is not modified' (двойные тапы)."""

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message


async def safe_edit(message: Message, text: str, reply_markup=None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
