"""
Support moderation for channel users: модерация комментариев под постами канала.
Технически комментарии живут в привязанной discussion-группе (chat.discussion_group_id),
поэтому основная фильтрация уже покрывается обычными модерационными хендлерами —
здесь регистрируется отдельная команда для действий «от имени канала».
Ответы — на языке чата (issue #12).
"""
import logging
from html import escape

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message

from bot.filters.roles import HasRole
from bot.utils.i18n import t

router = Router(name="channel_moderation")
logger = logging.getLogger(__name__)


@router.message(Command("banchannel"), HasRole("admin"))
async def ban_channel_commenter(message: Message, lang: str = "ru") -> None:
    """Банит sender_chat (анонимный канал), оставивший комментарий, из discussion-группы."""
    if not message.reply_to_message or not message.reply_to_message.sender_chat:
        await message.answer(t(lang, "banchannel_usage"))
        return
    channel_id = message.reply_to_message.sender_chat.id
    try:
        await message.bot.ban_chat_sender_chat(message.chat.id, channel_id)
    except TelegramAPIError as exc:
        # Только ошибки Telegram (issue #9): прочие исключения не должны превращаться в ответ в чат.
        logger.warning("Cannot ban sender chat %s in chat %s: %s", channel_id, message.chat.id, exc)
        await message.answer(t(lang, "banchannel_failed", error=escape(exc.message)))
        return
    await message.answer(t(lang, "banchannel_done"))
