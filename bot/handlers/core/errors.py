"""Глобальный обработчик ошибок Telegram API: вместо молчаливого падения хендлера
пользователь получает понятный ответ, ошибка пишется в лог (issue #45)."""
import logging

from aiogram import Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import ErrorEvent

from bot.services.chat_lang import get_chat_lang
from bot.utils.i18n import t

logger = logging.getLogger(__name__)


async def on_telegram_error(event: ErrorEvent) -> bool:
    message = event.update.message
    logger.warning("Telegram API error in update %s: %s", event.update.update_id, event.exception)
    if message is None:
        return True
    try:
        lang = await get_chat_lang(message.chat.id)
    except Exception:
        lang = "ru"
    try:
        await message.answer(t(lang, "telegram_error", error=event.exception.message), parse_mode=None)
    except TelegramAPIError:
        pass
    return True


def register_error_handlers(dp: Dispatcher) -> None:
    dp.errors.register(on_telegram_error, ExceptionTypeFilter(TelegramAPIError))
