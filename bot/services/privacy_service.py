"""
/forget и /forgetme (issue #36).

Раньше команды удаляли ChatUser (варны) и AuditLog (историю санкций), и нарушитель
мог сбросить себе варны одной командой. Теперь записи модерации сохраняются:
удаляется только то, что не нужно админам, а имя и username обезличиваются.

issue #92: счётчики сообщений участника (UserMessageStat) удаляются всегда —
они нужны только для топа активных, и после /forget человек не должен в нём остаться.
"""
from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import AuditLog, ChatUser, User, UserMessageStat


async def _moderated_chat_ids(session: AsyncSession, user_id: int, chat_id: int | None) -> set[int]:
    """Чаты, где у пользователя есть варны или история санкций."""
    audit = select(AuditLog.chat_id).where(AuditLog.target_user_id == user_id)
    warned = select(ChatUser.chat_id).where(ChatUser.user_id == user_id, ChatUser.warns > 0)
    if chat_id is not None:
        audit = audit.where(AuditLog.chat_id == chat_id)
        warned = warned.where(ChatUser.chat_id == chat_id)
    rows = (await session.execute(audit.union(warned))).scalars().all()
    return set(rows)


async def forget_user(session: AsyncSession, user_id: int, chat_id: int | None = None) -> bool:
    """
    Удаляет ChatUser без истории модерации (в одном чате или везде), счётчики сообщений
    участника и обезличивает User.
    Возвращает True, если записи модерации были сохранены. Не коммитит.
    """
    moderated = await _moderated_chat_ids(session, user_id, chat_id)
    stmt = delete(ChatUser).where(ChatUser.user_id == user_id)
    if chat_id is not None:
        stmt = stmt.where(ChatUser.chat_id == chat_id)
    if moderated:
        stmt = stmt.where(ChatUser.chat_id.not_in(moderated))
    await session.execute(stmt)

    stats_stmt = delete(UserMessageStat).where(UserMessageStat.user_id == user_id)
    if chat_id is not None:
        stats_stmt = stats_stmt.where(UserMessageStat.chat_id == chat_id)
    await session.execute(stats_stmt)

    await session.execute(update(User).where(User.id == user_id).values(username=None, full_name=""))
    return bool(moderated)
