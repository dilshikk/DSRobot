"""Group statistics: дневные счётчики + команда /stats.

Счётчики увеличиваются из moderation_pipeline (сообщения), service_events
(вступления/выходы) и apply_sanction (санкции). Сама логика — в services/stats.py (issue #47).

issue #92: /stats [today|week|month] — суммы за период, топ активных участников
и (для недели/месяца) текстовая гистограмма сообщений по дням.
"""
from __future__ import annotations

import html
from datetime import date

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.stats import (
    bump_stat,
    chat_today,
    daily_messages_query,
    fill_days,
    parse_period,
    period_bounds,
    render_histogram,
    top_users_query,
    totals_query,
)

__all__ = ["router", "bump_stat", "format_stats"]

router = Router(name="group_statistics")

USAGE = "Использование: /stats [today|week|month]"


def _display_name(user_id: int, username: str | None, full_name: str | None) -> str:
    if full_name:
        return html.escape(full_name)
    if username:
        return "@" + html.escape(username)
    return f"id{user_id}"


def format_stats(period: str, start: date, end: date, totals, top, series) -> str | None:
    """Текст ответа /stats (HTML). None, если за период ничего не было."""
    if not any(totals) and not top:
        return None
    title = "за сегодня" if period == "today" else f"за {start:%d.%m}\u2013{end:%d.%m}"
    messages, joins, leaves, sanctions = totals
    parts = [
        f"\U0001f4ca <b>Статистика {title}</b>",
        f"Сообщений: {messages}\nВступлений: {joins}\nВыходов: {leaves}\nСанкций: {sanctions}",
    ]
    if top:
        lines = [
            f"{i}. {_display_name(user_id, username, full_name)} \u2014 {total}"
            for i, (user_id, username, full_name, total) in enumerate(top, start=1)
        ]
        parts.append("<b>Самые активные:</b>\n" + "\n".join(lines))
    if series:
        parts.append("<b>Сообщения по дням:</b>\n<pre>" + html.escape(render_histogram(series)) + "</pre>")
    return "\n\n".join(parts)


@router.message(Command("stats"), HasRole("admin"))
async def show_stats(message: Message, command: CommandObject | None = None, chat_settings: dict | None = None) -> None:
    period = parse_period(command.args if command else None)
    if period is None:
        await message.answer(USAGE)
        return
    start, end = period_bounds(period, chat_today((chat_settings or {}).get("utc_offset", 0)))
    chat_id = message.chat.id
    async with SessionFactory() as session:
        totals = tuple((await session.execute(totals_query(chat_id, start, end))).one())
        top = (await session.execute(top_users_query(chat_id, start, end))).all()
        series = []
        if period != "today":
            rows = (await session.execute(daily_messages_query(chat_id, start, end))).all()
            series = fill_days(rows, start, end)
    text = format_stats(period, start, end, totals, top, series)
    if text is None:
        await message.answer("Статистики за этот период пока нет.")
        return
    await message.answer(text, parse_mode="HTML")
