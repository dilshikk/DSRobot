"""Group statistics: дневные счётчики + команда /stats.

Счётчики увеличиваются из moderation_pipeline (сообщения) и service_events
(вступления/выходы) — отдельные хендлеры перехватывали события у других модулей (issue #1).
Ответы — на языке чата (issue #12).
"""
from datetime import date

from aiogram import Router
from aiogram.filters import Command
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import GroupStat
from bot.filters.roles import HasRole
from bot.utils.i18n import t

router = Router(name="group_statistics")


async def bump_stat(chat_id: int, field: str) -> None:
    today = date.today()
    async with SessionFactory() as session:
        row = (await session.execute(
            select(GroupStat).where(GroupStat.chat_id == chat_id, GroupStat.date == today)
        )).scalar_one_or_none()
        if row is None:
            row = GroupStat(chat_id=chat_id, date=today)
            session.add(row)
        setattr(row, field, (getattr(row, field) or 0) + 1)
        await session.commit()


def stats_text(lang: str, row: GroupStat | None) -> str:
    if row is None:
        return t(lang, "stats_empty")
    return t(
        lang, "stats_today",
        messages=row.messages_count or 0, joins=row.joins_count or 0,
        leaves=row.leaves_count or 0, sanctions=row.sanctions_count or 0,
    )


@router.message(Command("stats"), HasRole("admin"))
async def show_stats(message, lang: str = "ru") -> None:
    today = date.today()
    async with SessionFactory() as session:
        row = (await session.execute(
            select(GroupStat).where(GroupStat.chat_id == message.chat.id, GroupStat.date == today)
        )).scalar_one_or_none()
    await message.answer(stats_text(lang, row), parse_mode="HTML")
