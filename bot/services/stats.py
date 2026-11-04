"""
Дневная статистика чата (issue #47) и отчёты по периоду (issue #92).

Раньше bump_stat делал read-modify-write: параллельные сообщения теряли инкременты,
а первое сообщение дня из двух параллельных апдейтов падало на uq_chat_date.
Теперь один атомарный INSERT ... ON CONFLICT DO UPDATE SET x = x + 1.

День считается в часовом поясе чата (Chat.utc_offset), а не сервера.

issue #92: счётчик сообщений по участнику (UserMessageStat) для топа активных,
суммы за неделю/месяц и ряд по дням для гистограммы.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database import SessionFactory
from bot.database.models import GroupStat, User, UserMessageStat

STAT_FIELDS = frozenset({"messages_count", "joins_count", "leaves_count", "sanctions_count"})

# Действия, которые считаются санкциями в статистике (снятие санкций не считается).
SANCTION_ACTIONS = frozenset({"warn", "mute", "ban", "kick"})

# Период отчёта /stats -> число дней, включая сегодня.
PERIOD_DAYS = {"today": 1, "week": 7, "month": 30}

# Как период можно написать в команде: /stats, /stats week, /stats неделя ...
PERIOD_ALIASES = {
    "": "today", "today": "today", "day": "today", "сегодня": "today", "день": "today",
    "week": "week", "неделя": "week", "7": "week",
    "month": "month", "месяц": "month", "30": "month",
}

TOP_LIMIT = 10


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


def user_message_upsert(chat_id: int, user_id: int, day: date):
    """Атомарный +1 к сообщениям участника за день (как stat_upsert)."""
    return (
        pg_insert(UserMessageStat)
        .values(chat_id=chat_id, user_id=user_id, date=day, messages_count=1)
        .on_conflict_do_update(
            constraint="uq_chat_user_date",
            set_={"messages_count": func.coalesce(UserMessageStat.messages_count, 0) + 1},
        )
    )


async def add_stat(session: AsyncSession, chat_id: int, field: str, utc_offset: int | None = 0) -> None:
    """Увеличивает счётчик в переданной сессии. Не коммитит."""
    await session.execute(stat_upsert(chat_id, field, chat_today(utc_offset)))


async def bump_stat(chat_id: int, field: str, utc_offset: int | None = 0) -> None:
    async with SessionFactory() as session:
        await add_stat(session, chat_id, field, utc_offset)
        await session.commit()


async def bump_message_stats(chat_id: int, user_id: int | None, utc_offset: int | None = 0) -> None:
    """
    Сообщение участника: +1 в group_stats и, если автор известен, +1 в user_message_stats.
    Одна сессия и один коммит на сообщение. user_id=None — анонимный админ или пост от
    имени канала: в общий счётчик попадает, в топ участников — нет.
    """
    day = chat_today(utc_offset)
    async with SessionFactory() as session:
        await session.execute(stat_upsert(chat_id, "messages_count", day))
        if user_id is not None:
            await session.execute(user_message_upsert(chat_id, user_id, day))
        await session.commit()


# --------------------------------------------------------------------------- #
# Отчёты /stats (issue #92)
# --------------------------------------------------------------------------- #

def parse_period(args: str | None) -> str | None:
    """Аргумент /stats -> 'today' | 'week' | 'month', None если не распознан."""
    return PERIOD_ALIASES.get((args or "").strip().lower())


def period_bounds(period: str, today: date) -> tuple[date, date]:
    """Первый и последний день периода включительно (today — дата в поясе чата)."""
    return today - timedelta(days=PERIOD_DAYS[period] - 1), today


def totals_query(chat_id: int, start: date, end: date):
    """Суммы счётчиков group_stats за период; всегда ровно одна строка."""
    return select(
        *(func.coalesce(func.sum(getattr(GroupStat, f)), 0).label(f) for f in (
            "messages_count", "joins_count", "leaves_count", "sanctions_count",
        ))
    ).where(GroupStat.chat_id == chat_id, GroupStat.date >= start, GroupStat.date <= end)


def daily_messages_query(chat_id: int, start: date, end: date):
    return (
        select(GroupStat.date, GroupStat.messages_count)
        .where(GroupStat.chat_id == chat_id, GroupStat.date >= start, GroupStat.date <= end)
        .order_by(GroupStat.date)
    )


def top_users_query(chat_id: int, start: date, end: date, limit: int = TOP_LIMIT):
    """
    Самые активные участники за период. Строки удалившихся через /forget уже стёрты
    (privacy_service), поэтому они в топ не попадают. outer join: имени может не быть.
    """
    total = func.sum(UserMessageStat.messages_count).label("total")
    return (
        select(UserMessageStat.user_id, User.username, User.full_name, total)
        .outerjoin(User, User.id == UserMessageStat.user_id)
        .where(
            UserMessageStat.chat_id == chat_id,
            UserMessageStat.date >= start,
            UserMessageStat.date <= end,
        )
        .group_by(UserMessageStat.user_id, User.username, User.full_name)
        .order_by(total.desc(), UserMessageStat.user_id)
        .limit(limit)
    )


def fill_days(rows, start: date, end: date) -> list[tuple[date, int]]:
    """Ряд по каждому дню периода; дни без записи в group_stats = 0."""
    counts = {day: count or 0 for day, count in rows}
    days = (end - start).days + 1
    return [(start + timedelta(days=i), counts.get(start + timedelta(days=i), 0)) for i in range(days)]


def render_histogram(series: list[tuple[date, int]], width: int = 12) -> str:
    """Текстовая гистограмма: '04.11 ██████ 12'. Ненулевой день всегда виден хотя бы чертой."""
    peak = max((count for _, count in series), default=0)
    lines = []
    for day, count in series:
        bar = "\u2588" * round(count / peak * width) if peak else ""
        if count and not bar:
            bar = "\u258f"
        lines.append(f"{day:%d.%m} {bar} {count}".replace("  ", " "))
    return "\n".join(lines)
