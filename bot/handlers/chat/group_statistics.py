"""Group statistics: дневные счётчики + команда /stats.

Счётчики увеличиваются из moderation_pipeline (сообщения), service_events
(вступления/выходы) и apply_sanction (санкции). Сама логика — в services/stats.py (issue #47).
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import GroupStat
from bot.filters.roles import HasRole
from bot.services.stats import bump_stat, chat_today

__all__ = ["router", "bump_stat"]

router = Router(name="group_statistics")


@router.message(Command("stats"), HasRole("admin"))
async def show_stats(message: Message, chat_settings: dict | None = None) -> None:
    today = chat_today((chat_settings or {}).get("utc_offset", 0))
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
