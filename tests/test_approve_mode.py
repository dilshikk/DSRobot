"""issue #50: режим одобрения не трогает старых участников; приветствие не падает на «{ }»."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram.types import Chat, Message, User

from bot.handlers.moderation import approve_mode
from bot.handlers.welcome.goodbye import goodbye_text
from bot.handlers.welcome.welcome import welcome_text


@pytest.mark.parametrize("template, expected", [
    ("Привет, {mention}!", "Привет, @bob!"),
    ("Привет, {name}!", "Привет, {name}!"),
    ("{} {mention}", "{} @bob"),
    ("Правила: {см. закреп}", "Правила: {см. закреп}"),
    ("{mention} и снова {mention}", "@bob и снова @bob"),
    ("{", "{"),
])
def test_custom_texts_with_braces_do_not_crash(template, expected):
    assert welcome_text({"text": template}, "ru", "@bob") == expected
    assert goodbye_text({"text": template}, "ru", "@bob") == expected


def test_escaped_variant_keeps_mention_html():
    text = welcome_text({"text": "<b>{mention}</b> {x}"}, "ru", '<a href="tg://user?id=1">Bob</a>', escape_custom=True)
    assert text == '&lt;b&gt;<a href="tg://user?id=1">Bob</a>&lt;/b&gt; {x}'


@pytest.mark.parametrize("row, blocked", [
    (None, False),                                                   # бот ещё не видел участника
    (SimpleNamespace(approved=False, pending_approval=False), False),  # старый участник
    (SimpleNamespace(approved=False, pending_approval=True), True),    # вступил при включённом режиме
    (SimpleNamespace(approved=True, pending_approval=True), False),
])
def test_needs_approval(row, blocked):
    assert approve_mode.needs_approval(row) is blocked


class FakeSession:
    def __init__(self, row=None):
        self.row, self.statements, self.commits = row, [], 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        self.statements.append(stmt)
        return SimpleNamespace(scalar_one_or_none=lambda: self.row)

    async def commit(self):
        self.commits += 1


class FakeRedis:
    def __init__(self):
        self.keys = set()

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.keys:
            return None
        self.keys.add(key)
        return True

    async def delete(self, *keys):
        self.keys.difference_update(keys)


@pytest.fixture
def env(monkeypatch):
    state = {"row": None, "deleted": [], "sent": [], "session": None}

    def session_factory():
        state["session"] = FakeSession(state["row"])
        return state["session"]

    async def delete(message, notify=True):
        state["deleted"].append(message.message_id)
        return True

    async def chat_lang(chat_id):
        return "en"

    async def upsert(session, user):
        return None

    monkeypatch.setattr(approve_mode, "SessionFactory", session_factory)
    monkeypatch.setattr(approve_mode, "delete_message_safely", delete)
    monkeypatch.setattr(approve_mode, "get_chat_lang", chat_lang)
    monkeypatch.setattr(approve_mode, "upsert_tg_user", upsert)
    monkeypatch.setattr(approve_mode, "redis", FakeRedis())
    return state


class FakeBot:
    def __init__(self, state):
        self.state = state

    async def send_message(self, chat_id, text, **kwargs):
        self.state["sent"].append(text)


def _msg(state, message_id=1):
    return Message.model_construct(
        message_id=message_id, date=datetime.now(), chat=Chat.model_construct(id=-100, type="supergroup"),
        from_user=User.model_construct(id=42, is_bot=False, first_name="Bob"), text="hi",
    ).as_(FakeBot(state))


ON = {"approve_mode": {"enabled": True}}


def test_existing_member_is_not_blocked(env):
    env["row"] = SimpleNamespace(approved=False, pending_approval=False)
    assert asyncio.run(approve_mode.check_unapproved(_msg(env), ON, "member")) is False
    assert env["deleted"] == []


def test_pending_member_is_blocked_and_notified_once(env):
    env["row"] = SimpleNamespace(approved=False, pending_approval=True)
    assert asyncio.run(approve_mode.check_unapproved(_msg(env, 1), ON, "member")) is True
    assert asyncio.run(approve_mode.check_unapproved(_msg(env, 2), ON, "member")) is True
    assert env["deleted"] == [1, 2]
    assert len(env["sent"]) == 1 and "approve" in env["sent"][0]


def test_disabled_mode_and_admins_skip_db(env):
    assert asyncio.run(approve_mode.check_unapproved(_msg(env), {}, "member")) is False
    assert asyncio.run(approve_mode.check_unapproved(_msg(env), ON, "admin")) is False
    assert env["session"] is None


def test_new_members_marked_only_when_enabled(env):
    members = [User.model_construct(id=1, is_bot=False, first_name="A"),
               User.model_construct(id=2, is_bot=True, first_name="B")]
    asyncio.run(approve_mode.mark_new_members_pending(-100, {}, members))
    assert env["session"] is None
    asyncio.run(approve_mode.mark_new_members_pending(-100, ON, members))
    assert len(env["session"].statements) == 1  # бот пропущен
    assert env["session"].commits == 1
