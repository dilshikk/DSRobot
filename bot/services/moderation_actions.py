"""
Единая точка применения санкций (ban/mute/kick/warn/unmute/unban), используется
и командами модерации, и авто-модулями (antiflood, antispam, banned_words, anti_nsfw).
Пишет в AuditLog и, если настроен log_channel, шлёт туда уведомление —
Log channel feature.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.types import ChatPermissions
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import AuditLog, Chat, ChatUser

MUTED_PERMISSIONS = ChatPermissions(can_send_messages=False)
UNMUTED_PERMISSIONS = ChatPermissions(
    can_send_messages=True, can_send_audios=True, can_send_documents=True,
    can_send_photos=True, can_send_videos=True, can_send_other_messages=True,
)


async def apply_sanction(
    bot: Bot,
    chat_id: int,
    user_id: int,
    action: str,
    reason: str = "",
    actor_user_id: int = 0,
    duration_minutes: int | None = None,
) -> None:
    until = None
    if duration_minutes:
        until = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)

    try:
        if action == "ban":
            await bot.ban_chat_member(chat_id, user_id, until_date=until)
        elif action == "kick":
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id)
        elif action == "mute":
            await bot.restrict_chat_member(chat_id, user_id, MUTED_PERMISSIONS, until_date=until)
        elif action == "unmute":
            await bot.restrict_chat_member(chat_id, user_id, UNMUTED_PERMISSIONS)
        elif action == "unban":
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
        # action == "warn" не требует Telegram API вызова — только счётчик в БД
    except Exception:
        # Недостаточно прав у бота / пользователь уже вышел и т.п. — не роняем обработчик.
        pass

    async with SessionFactory() as session:
        session.add(AuditLog(chat_id=chat_id, target_user_id=user_id, actor_user_id=actor_user_id,
                              action=action, reason=reason))

        cu = (await session.execute(
            select(ChatUser).where(ChatUser.chat_id == chat_id, ChatUser.user_id == user_id)
        )).scalar_one_or_none()
        if cu is None:
            cu = ChatUser(chat_id=chat_id, user_id=user_id)
            session.add(cu)

        if action == "warn":
            cu.warns += 1
        elif action == "mute":
            cu.muted_until = until
        elif action == "ban":
            cu.banned_until = until
        elif action in ("unmute", "unban"):
            cu.muted_until = None
            cu.banned_until = None

        await session.commit()

        chat = await session.get(Chat, chat_id)

    if chat and chat.log_channel_id:
        try:
            await bot.send_message(
                chat.log_channel_id,
                f"\U0001f6e1 <b>{action.upper()}</b>\n"
                f"Chat: <code>{chat_id}</code>\nUser: <code>{user_id}</code>\n"
                f"By: <code>{actor_user_id or 'auto'}</code>\nReason: {reason or '—'}",
                parse_mode="HTML",
            )
        except Exception:
            pass
