"""issue #47: статистика без гонок и по дате чата, sanctions_count считается,
/inactive и /tagall смотрят на активность в этом чате и не включают вышедших."""
import asyncio
import re
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from aiogram.types import Chat, Message, PhotoSize, User
from sqlalchemy.dialects import postgresql

from bot.handlers.chat import members_management
from bot.middlewares import moderation_pipeline as mp
from bot.services import moderation_actions as ma
from bot.services import stats, user_service


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


@pytest.mark.parametrize("offset, expected", [
    (0, date(2026, 1, 1)), (3, date(2026, 1, 2)), (-5, date(2026, 1, 1)), (None, date(2026, 1, 1)),
])
def test_chat_today_uses_chat_offset(offset, expected):
    now = datetime(2026, 1, 1, 22, 30, tzinfo=timezone.utc)
    assert stats.chat_today(offset, now) == expected


def test_stat_upsert_is_atomic_increment():
    # SQLAlchemy не подставляет literal_binds в ON CONFLICT ... SET, поэтому параметры
    # остаются плейсхолдерами. Проверяем саму форму: x = coalesce(x, ?) + ?
    sql = _sql(stats.stat_upsert(-100, "messages_count", date(2026, 1, 1)))
    assert "ON CONFLICT ON CONSTRAINT uq_chat_date DO UPDATE" in sql
    assert re.search(r"SET messages_count = \(?coalesce\(group_stats\.messages_count, [^)]+\) \+ ", sql)


def test_stat_upsert_rejects_unknown_field():
    with pytest.raises(ValueError):
        stats.stat_upsert(-100, "id", date(2026, 1, 1))


def test_inactive_query_is_per_chat_and_skips_left_members():
    sql = _sql(members_management.inactive_members_query(-100, datetime(2026, 1, 1, tzinfo=timezone.utc)))
    assert "coalesce(chat_users.last_seen_at, chat_users.joined_at)" in sql
    assert "chat_users.left_at IS NULL" in sql
    # Глобальный users.last_seen не используется (подстрока chat_users.last_seen_at не в счёт).
    assert not re.search(r"(?<![\w.])users\.last_seen\b", sql)


class RecordingSession:
    def __init__(self, chat=None, chat_user=None):
        self.statements, self.added, self.commits = [], [], 0
        self.chat = chat
        self.chat_user = chat_user or SimpleNamespace(warns=0, muted_until=None, banned_until=None, left_at=None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        self.statements.append(stmt)
        return SimpleNamespace(scalar_one=lambda: self.chat_user)

    def add(self, row):
        self.added.append(row)

    async def get(self, model, key):
        return self.chat

    async def commit(self):
        self.commits += 1


def test_sanction_does_not_touch_last_seen():
    session = RecordingSession()
    asyncio.run(user_service.upsert_user(session, 42, touch=False))
    sql = _sql(session.statements[0])
    assert "last_seen" not in sql
    assert "DO NOTHING" in sql


def test_regular_upsert_touches_last_seen():
    session = RecordingSession()
    asyncio.run(user_service.upsert_user(session, 42, "bob", "Bob"))
    assert "last_seen" in _sql(session.statements[0])


@pytest.fixture
def sanction_env(monkeypatch):
    session = RecordingSession(chat=SimpleNamespace(utc_offset=3, log_channel_id=None))
    bumps: list[tuple] = []

    async def call_telegram(*args, **kwargs):
        return None

    async def add_stat(sess, chat_id, field, utc_offset=0):
        bumps.append((chat_id, field, utc_offset))

    monkeypatch.setattr(ma, "_call_telegram", call_telegram)
    monkeypatch.setattr(ma, "SessionFactory", lambda: session)
    monkeypatch.setattr(ma, "add_stat", add_stat)
    return session, bumps


@pytest.mark.parametrize("action", ["warn", "mute", "ban", "kick"])
def test_sanctions_are_counted(sanction_env, action):
    session, bumps = sanction_env
    assert asyncio.run(ma.apply_sanction(object(), -100, 42, action)) is None
    assert bumps == [(-100, "sanctions_count", 3)]
    assert session.commits == 1


@pytest.mark.parametrize("action", ["unmute", "unban"])
def test_lifting_sanctions_is_not_counted(sanction_env, action):
    _, bumps = sanction_env
    asyncio.run(ma.apply_sanction(object(), -100, 42, action))
    assert bumps == []


@pytest.mark.parametrize("action, left", [("ban", True), ("kick", True), ("mute", False)])
def test_ban_and_kick_mark_member_left(sanction_env, action, left):
    session, _ = sanction_env
    asyncio.run(ma.apply_sanction(object(), -100, 42, action))
    assert (session.chat_user.left_at is not None) is left


def test_media_without_text_is_counted(monkeypatch):
    bumps: list[tuple] = []

    async def fake_bump(chat_id, field, utc_offset=0):
        bumps.append((field, utc_offset))

    monkeypatch.setattr(mp, "bump_stat", fake_bump)
    monkeypatch.setattr(mp, "MESSAGE_CHECKS", [])
    message = Message.model_construct(
        message_id=1, date=datetime.now(), chat=Chat.model_construct(id=-100, type="supergroup"),
        from_user=User.model_construct(id=42, is_bot=False, first_name="T"),
        photo=[PhotoSize(file_id="p", file_unique_id="p", width=1, height=1)],
    )

    async def handler(event, data):
        return "handled"

    data = {"chat_settings": {"utc_offset": 5}, "chat_user_role": "member"}
    assert asyncio.run(mp.ModerationPipelineMiddleware()(handler, message, data)) == "handled"
    assert bumps == [("messages_count", 5)]
