"""
Дневная статистика чата (issue #47).

Раньше bump_stat делал read-modify-write: параллельные сообщения теряли инкременты,
а первое сообщение дня из двух параллельных апдейтов падало на uq_chat_date.
Теперь один атомарный INSERT ... ON CONFLICT DO UPDATE SET x = x + 1.

День считается в часовом поясе чата (Chat.utc_offset), а не сервера.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database import SessionFactory
from bot.database.models import GroupStat

STAT_FIELDS = frozenset({"messages_count", "joins_count", "leaves_count", "sanctions_count"})

# Действия, которые считаются санкциями в статистике (снятие санкций не считается).
SANCTION_ACTIONS = frozenset({"warn", "mute", "ban", "kick"})


def chat_today(utc_offset: int | None = 0, now: datetime | None = None) -> date:
    """Текущая дата в часовом поясе чата."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return (now + timedelta(hours=utc_offset or 0)).date()


def stat_upsert(chat_id: int, field: str, day: date):
    if field not in STAT_FIELDS:
        raise ValueError(f"Unknown stat field: {field}")
    column = getattr(GroupStat, field)
    return (
        pg_insert(GroupStat)
        .values(chat_id=chat_id, date=day, **{field: 1})
        .on_conflict_do_update(constraint="uq_chat_date", set_={field: func.coalesce(column, 0) + 1})
    )


async def add_stat(session: AsyncSession, chat_id: int, field: str, utc_offset: int | None = 0) -> None:
    """Увеличивает счётчик в переданной сессии. Не коммитит."""
    await session.execute(stat_upsert(chat_id, field, chat_today(utc_offset)))


async def bump_stat(chat_id: int, field: str, utc_offset: int | None = 0) -> None:
    async with SessionFactory() as session:
        await add_stat(session, chat_id, field, utc_offset)
        await session.commit()
