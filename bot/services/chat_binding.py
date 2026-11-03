"""
issue #46: безопасная привязка внешних чатов и лимиты /report.

/setlogchannel, /setstaffgroup и /linkdiscussion раньше сохраняли любой chat_id, и владелец
одной группы мог направить логи и репорты в чужой чат, где бот админ. Теперь целевой чат
проверяется: вызывающий должен быть его админом, а бот должен иметь возможность туда писать.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from bot.services.cache import incr_with_ttl, redis

logger = logging.getLogger(__name__)

ADMIN_STATUSES = frozenset({"creator", "administrator"})
GONE_STATUSES = frozenset({"left", "kicked"})

REPORT_USER_COOLDOWN = 60          # сек между репортами одного пользователя в чате
REPORT_CHAT_WINDOW = 60            # окно для лимита репортов на чат
REPORT_CHAT_LIMIT = 10             # репортов на чат за окно
REPORT_DUPLICATE_TTL = 24 * 3600   # сколько помним, что сообщение уже зарепорчено

ANONYMOUS_CALLER = (
    "Не могу проверить ваши права: команда отправлена анонимно. "
    "Отключите анонимность администратора и повторите."
)
SAME_CHAT = "Нельзя указать этот же чат."
TARGET_UNREACHABLE = "Бот не видит указанный чат. Добавьте бота туда администратором и повторите."
CALLER_NOT_ADMIN = "Вы должны быть администратором указанного чата."
BOT_CANNOT_POST = "Бот не может писать в указанный чат. Выдайте ему права администратора."
BOT_NOT_ADMIN = "Бот должен быть администратором указанного чата."

REPORT_DUPLICATE = "На это сообщение уже пожаловались."
REPORT_USER_COOLDOWN_TEXT = "Слишком часто. Следующий репорт можно отправить через минуту."
REPORT_CHAT_LIMIT_TEXT = "Слишком много репортов в чате. Попробуйте позже."


def caller_id(message: Message) -> int | None:
    """id живого пользователя. Анонимного админа или канал проверить в чужом чате нельзя."""
    if message.sender_chat is not None or message.from_user is None:
        return None
    return message.from_user.id


def bot_can_post(chat_type: str, member: object) -> bool:
    status = getattr(member, "status", None)
    if chat_type == "channel":
        return status in ADMIN_STATUSES and bool(getattr(member, "can_post_messages", False))
    if status in GONE_STATUSES:
        return False
    if status == "restricted":
        return bool(getattr(member, "is_member", False)) and bool(getattr(member, "can_send_messages", False))
    return status is not None


async def verify_target(
    bot: Bot,
    message: Message,
    target_id: int,
    *,
    bot_must_be_admin: bool = False,
) -> str | None:
    """Возвращает текст ошибки или None, если привязать target_id к текущему чату безопасно."""
    if target_id == message.chat.id:
        return SAME_CHAT
    user_id = caller_id(message)
    if user_id is None:
        return ANONYMOUS_CALLER
    try:
        target = await bot.get_chat(target_id)
        user_member = await bot.get_chat_member(target_id, user_id)
        bot_member = await bot.get_chat_member(target_id, bot.id)
    except TelegramAPIError as exc:
        logger.info("Cannot verify chat %s for chat %s: %s", target_id, message.chat.id, exc)
        return TARGET_UNREACHABLE
    if user_member.status not in ADMIN_STATUSES:
        return CALLER_NOT_ADMIN
    if bot_must_be_admin and bot_member.status not in ADMIN_STATUSES:
        return BOT_NOT_ADMIN
    if not bot_can_post(target.type, bot_member):
        return BOT_CANNOT_POST
    return None


def _duplicate_key(chat_id: int, message_id: int) -> str:
    return f"report:msg:{chat_id}:{message_id}"


async def reserve_report(chat_id: int, reporter_id: int, message_id: int, *, privileged: bool = False) -> str | None:
    """
    Резервирует репорт: возвращает текст отказа или None.
    Админы не ограничены кулдауном, но тоже не могут повторно репортить одно сообщение.
    """
    duplicate_key = _duplicate_key(chat_id, message_id)
    if await redis.exists(duplicate_key):
        return REPORT_DUPLICATE
    if not privileged:
        user_key = f"report:user:{chat_id}:{reporter_id}"
        if not await redis.set(user_key, 1, ex=REPORT_USER_COOLDOWN, nx=True):
            return REPORT_USER_COOLDOWN_TEXT
        if await incr_with_ttl(f"report:chat:{chat_id}", REPORT_CHAT_WINDOW) > REPORT_CHAT_LIMIT:
            return REPORT_CHAT_LIMIT_TEXT
    # SET NX защищает от гонки двух одновременных репортов одного сообщения.
    if not await redis.set(duplicate_key, 1, ex=REPORT_DUPLICATE_TTL, nx=True):
        return REPORT_DUPLICATE
    return None


async def release_report(chat_id: int, message_id: int) -> None:
    """Снимает отметку, если репорт не удалось доставить, чтобы его можно было повторить."""
    await redis.delete(_duplicate_key(chat_id, message_id))
