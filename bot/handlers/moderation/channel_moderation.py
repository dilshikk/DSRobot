"""
Support moderation for channel users: модерация комментариев под постами канала.
Технически комментарии живут в привязанной discussion-группе (chat.discussion_group_id),
поэтому основная фильтрация уже покрывается обычными модерационными хендлерами —
здесь регистрируется отдельная команда для действий «от имени канала».
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.filters.roles import HasRole

router = Router(name="channel_moderation")


@router.message(Command("banchannel"), HasRole("admin"))
async def ban_channel_commenter(message: Message) -> None:
    """Банит sender_chat (анонимный канал), оставивший комментарий, из discussion-группы."""
    if not message.reply_to_message or not message.reply_to_message.sender_chat:
        await message.answer("Ответьте на комментарий, оставленный от имени канала.")
        return
    channel_id = message.reply_to_message.sender_chat.id
    try:
        await message.bot.ban_chat_sender_chat(message.chat.id, channel_id)
        await message.answer("\u2705 Канал заблокирован в этой группе.")
    except Exception as exc:
        await message.answer(f"\u26a0\ufe0f Не удалось: {exc}")
