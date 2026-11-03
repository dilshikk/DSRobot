"""Group statistics: инкремент дневных счётчиков + команда /stats."""
from datetime import date

from aiogram import Router, F
from aiogram.filters import Command
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import GroupStat
from bot.filters.roles import HasRole

router = Router(name="group_statistics")


async def _bump(chat_id: int, field: str) -> None:
    today = date.today()
    async with SessionFactory() as session:
        row = (await session.execute(
            select(GroupStat).where(GroupStat.chat_id == chat_id, GroupStat.date == today)
        )).scalar_one_or_none()
        if row is None:
            row = GroupStat(chat_id=chat_id, date=today)
            session.add(row)
        setattr(row, field, getattr(row, field) + 1)
        await session.commit()


@router.message(F.text, ~F.text.startswith("/"))
async def count_message(message) -> None:
    await _bump(message.chat.id, "messages_count")


@router.message(F.new_chat_members)
async def count_join(message) -> None:
    await _bump(message.chat.id, "joins_count")


@router.message(F.left_chat_member)
async def count_leave(message) -> None:
    await _bump(message.chat.id, "leaves_count")


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
