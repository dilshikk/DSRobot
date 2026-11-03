"""
Сохранение пользователей и их связи с чатом.

ChatUser.user_id ссылается на users.id (ForeignKey), поэтому строку User нужно
создать раньше, чем ChatUser — иначе INSERT падает (см. issue #4).
Используем PostgreSQL upsert (ON CONFLICT), чтобы не ловить гонки при
параллельной обработке апдейтов от одного пользователя.
"""
from __future__ import annotations

from aiogram.types import User as TgUser
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ChatUser, User


async def upsert_user(
    session: AsyncSession,
    user_id: int,
    username: str | None = None,
    full_name: str | None = None,
) -> None:
    """Создаёт User или обновляет username/full_name/last_seen. Не коммитит."""
    values: dict = {"id": user_id, "full_name": full_name or "", "username": username}
    stmt = pg_insert(User).values(**values)

    update_set: dict = {"last_seen": func.now()}
    # Если данные Telegram неизвестны (например, санкция по одному id) — не затираем их.
    if full_name is not None:
        update_set["full_name"] = full_name
        update_set["username"] = username

    stmt = stmt.on_conflict_do_update(index_elements=[User.id], set_=update_set)
    await session.execute(stmt)


async def upsert_tg_user(session: AsyncSession, tg_user: TgUser) -> None:
    await upsert_user(session, tg_user.id, tg_user.username, tg_user.full_name)


async def ensure_chat_user(session: AsyncSession, chat_id: int, user_id: int) -> ChatUser:
    """Возвращает ChatUser, создавая его с warns=0 при отсутствии. Не коммитит.

    Предполагается, что User и Chat уже существуют (FK).
    """
    stmt = (
        pg_insert(ChatUser)
        .values(chat_id=chat_id, user_id=user_id, warns=0, role="member", approved=False)
        .on_conflict_do_nothing(constraint="uq_chat_user")
    )
    await session.execute(stmt)

    return (await session.execute(
        select(ChatUser).where(ChatUser.chat_id == chat_id, ChatUser.user_id == user_id)
    )).scalar_one()
