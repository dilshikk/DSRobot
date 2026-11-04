"""issue #92: /stats week|month, топ активных участников, гистограмма, исключение после /forget."""
import asyncio
import re
from datetime import date, datetime

import pytest
from aiogram.types import Chat, Message, User
from sqlalchemy.dialects import postgresql

from bot.handlers.chat.group_statistics import format_stats
from bot.middlewares import moderation_pipeline as mp
from bot.services import stats
from bot.services.privacy_service import forget_user

DAY = date(2026, 11, 4)


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


@pytest.mark.parametrize("arg, period", [
    (None, "today"), ("", "today"), ("week", "week"), (" WEEK ", "week"), ("неделя", "week"),
    ("month", "month"), ("месяц", "month"), ("year", None), ("week extra", None),
])
def test_parse_period(arg, period):
    assert stats.parse_period(arg) == period


@pytest.mark.parametrize("period, start", [
    ("today", DAY), ("week", date(2026, 10, 29)), ("month", date(2026, 10, 6)),
])
def test_period_bounds_are_inclusive(period, start):
    assert stats.period_bounds(period, DAY) == (start, DAY)


def test_totals_query_sums_period_for_chat():
    sql = _sql(stats.totals_query(-100, date(2026, 10, 29), DAY))
    for field in ("messages_count", "joins_count", "leaves_count", "sanctions_count"):
        assert f"coalesce(sum(group_stats.{field}), 0)" in sql
    assert "group_stats.chat_id = -100" in sql
    assert "group_stats.date >= '2026-10-29'" in sql and "group_stats.date <= '2026-11-04'" in sql


def test_top_users_query_groups_orders_and_limits():
    sql = _sql(stats.top_users_query(-100, date(2026, 10, 29), DAY, limit=5))
    assert "sum(user_message_stats.messages_count)" in sql
    assert "LEFT OUTER JOIN users" in sql
    assert "user_message_stats.chat_id = -100" in sql
    assert "user_message_stats.date >= '2026-10-29'" in sql
    assert re.search(r"GROUP BY user_message_stats\.user_id", sql)
    assert re.search(r"ORDER BY total DESC", sql)
    assert "LIMIT 5" in sql


def test_user_message_upsert_is_atomic_increment():
    sql = _sql(stats.user_message_upsert(-100, 42, DAY))
    assert "ON CONFLICT ON CONSTRAINT uq_chat_user_date DO UPDATE" in sql
    assert re.search(r"SET messages_count = \(?coalesce\(user_message_stats\.messages_count, .+?\) \+ ", sql)


def test_fill_days_adds_missing_days_as_zero():
    rows = [(date(2026, 11, 2), 5), (date(2026, 11, 4), 3)]
    assert stats.fill_days(rows, date(2026, 11, 1), DAY) == [
        (date(2026, 11, 1), 0), (date(2026, 11, 2), 5), (date(2026, 11, 3), 0), (date(2026, 11, 4), 3),
    ]


def test_histogram_scales_to_peak_and_shows_small_days():
    lines = stats.render_histogram([(date(2026, 11, 1), 0), (date(2026, 11, 2), 100), (date(2026, 11, 3), 1)],
                                   width=10).splitlines()
    assert lines[0] == "01.11 0"
    assert lines[1] == "02.11 " + "\u2588" * 10 + " 100"
    assert lines[2] == "03.11 \u258f 1"  # 1 из 100 округляется в 0, но день не должен выглядеть пустым


def test_histogram_all_zero():
    assert stats.render_histogram([(DAY, 0)]) == "04.11 0"


def test_format_stats_empty_period():
    assert format_stats("week", date(2026, 10, 29), DAY, (0, 0, 0, 0), [], []) is None


def test_format_stats_top_escapes_names_and_falls_back_to_id():
    top = [(1, "bob", "<b>Bob</b>", 30), (2, "alice", "", 20), (3, None, "", 10)]
    text = format_stats("week", date(2026, 10, 29), DAY, (60, 1, 0, 2), top,
                        [(DAY, 60)])
    assert "за 29.10\u201304.11" in text
    assert "Сообщений: 60" in text and "Санкций: 2" in text
    assert "1. &lt;b&gt;Bob&lt;/b&gt; \u2014 30" in text
    assert "2. @alice \u2014 20" in text
    assert "3. id3 \u2014 10" in text
    assert "<pre>" in text


def test_format_stats_today_has_no_histogram():
    text = format_stats("today", DAY, DAY, (5, 0, 0, 0), [], [])
    assert "за сегодня" in text and "<pre>" not in text


# --------------------------------------------------------------------------- #
# Счётчик по участнику в moderation_pipeline
# --------------------------------------------------------------------------- #

def _msg(sender_chat=None) -> Message:
    return Message.model_construct(
        message_id=1, date=datetime.now(), chat=Chat.model_construct(id=-100, type="supergroup"),
        from_user=User.model_construct(id=42, is_bot=False, first_name="T"), text="hi", sender_chat=sender_chat,
    )


@pytest.mark.parametrize("sender_chat, author", [
    (None, 42),
    (Chat.model_construct(id=-100, type="supergroup"), None),  # анонимный админ
])
def test_pipeline_counts_author(monkeypatch, sender_chat, author):
    bumps = []

    async def fake_bump(chat_id, user_id, utc_offset=0):
        bumps.append((chat_id, user_id, utc_offset))

    monkeypatch.setattr(mp, "bump_message_stats", fake_bump)
    monkeypatch.setattr(mp, "MESSAGE_CHECKS", [])

    async def handler(event, data):
        return "handled"

    data = {"chat_settings": {"utc_offset": 2}, "chat_user_role": "member"}
    asyncio.run(mp.ModerationPipelineMiddleware()(handler, _msg(sender_chat), data))
    assert bumps == [(-100, author, 2)]


# --------------------------------------------------------------------------- #
# /forget убирает участника из топа
# --------------------------------------------------------------------------- #

class FakeSession:
    def __init__(self, moderated):
        self.moderated = moderated
        self.sql: list[str] = []

    async def execute(self, stmt):
        self.sql.append(_sql(stmt))
        rows = self.moderated if self.sql[-1].lstrip().startswith("SELECT") else []
        return type("R", (), {"scalars": lambda s: s, "all": lambda s: rows})()


def _stats_deletes(session):
    return [s for s in session.sql if s.startswith("DELETE FROM user_message_stats")]


@pytest.mark.parametrize("moderated", [[], [-100]])
def test_forget_in_chat_deletes_message_stats_even_with_warns(moderated):
    session = FakeSession(moderated)
    asyncio.run(forget_user(session, 42, -100))
    (stmt,) = _stats_deletes(session)
    assert "user_message_stats.user_id = 42" in stmt and "user_message_stats.chat_id = -100" in stmt


def test_forgetme_deletes_message_stats_everywhere():
    session = FakeSession([])
    asyncio.run(forget_user(session, 42))
    (stmt,) = _stats_deletes(session)
    assert "user_message_stats.user_id = 42" in stmt and "chat_id" not in stmt
