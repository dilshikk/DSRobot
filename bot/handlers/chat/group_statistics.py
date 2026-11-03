"""Group statistics: дневные счётчики + команда /stats.

Счётчики увеличиваются из moderation_pipeline (сообщения) и service_events
(вступления/выходы) — отдельные хендлеры перехватывали события у других модулей (issue #1).
"""
from datetime import date

from aiogram import Router
from aiogram.filters import Command
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import GroupStat
from bot.filters.roles import HasRole

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


@router.message(Command("stats"), HasRole("admin"))
async def show_stats(message) -> None:
    today = date.today()
    async with SessionFactory() as session:
        row = (await session.execute(
            select(GroupStat).where(GroupStat.chat_id == message.chat.id, GroupStat.date == today)
        )).scalar_one_or_none()
    if not row:
        await message.answer("Статистики за сегодня пока нет.")
        return
    await message.answer(
        f"\U0001f4ca <b>Статистика за сегодня</b>\n"
        f"Сообщений: {row.messages_count}\nВступлений: {row.joins_count}\n"
        f"Выходов: {row.leaves_count}\nСанкций: {row.sanctions_count}",
        parse_mode="HTML",
    )
