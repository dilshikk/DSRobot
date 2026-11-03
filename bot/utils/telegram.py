"""
Безопасные вызовы Telegram API без молчаливого подавления ошибок (issue #9).

Раньше по проекту было `except Exception: pass`: ошибки прав бота, сети и логики
пропадали бесследно. Здесь ошибки перехватываются по типу и пишутся в лог (а через
лог — в Sentry). Если боту не хватает прав, в чат один раз в несколько часов
приходит понятное сообщение для админов.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

from bot.services.cache import redis

logger = logging.getLogger(__name__)

# Как часто (сек) напоминать админам чата, что у бота не хватает прав.
RIGHTS_NOTICE_TTL = 6 * 3600
NO_RIGHTS_MARKERS = ("not enough rights", "have no rights", "chat_admin_required")
# Сообщение уже удалено (другим админом, автоудалением) — это не ошибка.
ALREADY_GONE_MARKERS = ("message to delete not found", "message_id_invalid")


def is_rights_error(exc: TelegramBadRequest) -> bool:
    text = exc.message.lower()
    return any(marker in text for marker in NO_RIGHTS_MARKERS)


def _is_already_gone(exc: TelegramBadRequest) -> bool:
    text = exc.message.lower()
    return any(marker in text for marker in ALREADY_GONE_MARKERS)


async def notify_missing_rights(bot: Bot, chat_id: int, action: str) -> None:
    """Сообщает в чат, что боту не хватает прав. Не чаще раза в RIGHTS_NOTICE_TTL."""
    is_first = await redis.set(f"rights_notice:{chat_id}", 1, ex=RIGHTS_NOTICE_TTL, nx=True)
    if not is_first:
        return
    try:
        await bot.send_message(
            chat_id,
            f"\u26a0\ufe0f У бота не хватает прав, чтобы {action}. "
            "Выдайте боту права администратора на удаление сообщений и блокировку участников.",
        )
    except TelegramAPIError as exc:
        logger.warning("Cannot send missing-rights notice to chat %s: %s", chat_id, exc)


async def _handle_delete_error(bot: Bot, chat_id: int, message_id: int, exc: TelegramAPIError,
                               notify: bool) -> None:
    if isinstance(exc, TelegramBadRequest):
        if _is_already_gone(exc):
            return
        logger.warning("Cannot delete message %s in chat %s: %s", message_id, chat_id, exc)
        if notify and is_rights_error(exc):
            await notify_missing_rights(bot, chat_id, "удалять сообщения")
    elif isinstance(exc, TelegramForbiddenError):
        logger.warning("Bot was removed from chat %s, cannot delete message %s: %s", chat_id, message_id, exc)
    else:
        logger.error("Failed to delete message %s in chat %s: %s", message_id, chat_id, exc)


async def delete_message_safely(message: Message, notify: bool = True) -> bool:
    """Удаляет сообщение. Возвращает True при успехе, ошибки логирует."""
    try:
        await message.delete()
        return True
    except TelegramAPIError as exc:
        await _handle_delete_error(message.bot, message.chat.id, message.message_id, exc, notify)
        return False


async def delete_by_id_safely(bot: Bot, chat_id: int, message_id: int, notify: bool = False) -> bool:
    """Удаляет сообщение по id (капча, старое приветствие). Ошибки логирует."""
    try:
        await bot.delete_message(chat_id, message_id)
        return True
    except TelegramAPIError as exc:
        await _handle_delete_error(bot, chat_id, message_id, exc, notify)
        return False
