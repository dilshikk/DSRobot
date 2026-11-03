"""issue #49: порог считает первое сообщение, дубли удаляются, счётчик атомарен."""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram.types import Chat, Message, User

from bot.handlers.moderation import antispam
from bot.services import cache


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = str(value)
        return True

    async def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)

    async def incr(self, key):
        self.data[key] = str(int(self.data.get(key, 0)) + 1)
        return int(self.data[key])


@pytest.fixture
def env(monkeypatch):
    fake = FakeRedis()
    deleted, sanctions = [], []

    async def get_json(key):
        raw = await fake.get(key)
        return json.loads(raw) if raw else None

    async def set_json(key, value, ex=None):
        await fake.set(key, json.dumps(value), ex=ex)

    async def incr_with_ttl(key, ttl):
        return await fake.incr(key)

    async def delete_by_id(bot, chat_id, message_id, notify=False):
        deleted.append(message_id)
        return True

    async def apply_sanction(bot, chat_id, user_id, action, reason, actor, duration_minutes=None, lang="ru"):
        sanctions.append((action, duration_minutes))

    async def get_chat_lang(chat_id):
        return "ru"

    for name, value in {
        "redis": fake, "get_json": get_json, "set_json": set_json, "incr_with_ttl": incr_with_ttl,
        "delete_by_id_safely": delete_by_id, "apply_sanction": apply_sanction, "get_chat_lang": get_chat_lang,
    }.items():
        monkeypatch.setattr(antispam, name, value)
    return deleted, sanctions


def _msg(message_id: int, text: str = "buy now") -> Message:
    return Message.model_construct(
        message_id=message_id, date=datetime.now(), chat=Chat.model_construct(id=-100, type="supergroup"),
        from_user=User.model_construct(id=42, is_bot=False, first_name="S"), text=text,
    )


def _check(message, settings=None):
    settings = settings or {"antispam": {"enabled": True}}
    return asyncio.run(antispam.check_duplicate_spam(message, settings, "member"))


def test_mute_on_third_identical_message_and_all_copies_deleted(env):
    deleted, sanctions = env
    assert _check(_msg(1)) is False
    assert _check(_msg(2)) is False
    assert _check(_msg(3)) is True
    assert sorted(deleted) == [1, 2, 3]
    assert sanctions == [("mute", antispam.DEFAULT_MUTE_MINUTES)]


def test_different_message_resets_series(env):
    deleted, sanctions = env
    _check(_msg(1))
    _check(_msg(2))
    _check(_msg(3, "hello"))
    assert _check(_msg(4)) is False
    assert deleted == [] and sanctions == []


def test_custom_threshold_and_duration(env):
    deleted, sanctions = env
    settings = {"antispam": {"enabled": True, "duplicate_threshold": 2, "mute_minutes": 5}}
    assert _check(_msg(1), settings) is False
    assert _check(_msg(2), settings) is True
    assert sanctions == [("mute", 5)]


def test_admins_and_disabled_are_skipped(env):
    _, sanctions = env
    for _ in range(5):
        assert asyncio.run(antispam.check_duplicate_spam(_msg(1), {"antispam": {"enabled": True}}, "admin")) is False
        assert _check(_msg(1), {"antispam": {"enabled": False}}) is False
    assert sanctions == []


@pytest.mark.parametrize("args, parsed", [
    ("3", (3, antispam.DEFAULT_MUTE_MINUTES)), ("5 60", (5, 60)),
    ("1", None), ("21", None), ("3 0", None), ("x", None), ("", None), (None, None), ("3 5 7", None),
])
def test_parse_args(args, parsed):
    assert antispam.parse_antispam_args(args) == parsed


def test_bad_stored_limits_fall_back_to_defaults():
    assert antispam.antispam_limits({"duplicate_threshold": "x", "mute_minutes": 0}) == (
        antispam.DEFAULT_THRESHOLD, antispam.DEFAULT_MUTE_MINUTES)


def test_incr_with_ttl_sets_ttl_and_increments_in_one_transaction(monkeypatch):
    calls = []

    class Pipe:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def set(self, key, value, ex=None, nx=False):
            calls.append(("set", key, value, ex, nx))

        def incr(self, key):
            calls.append(("incr", key))

        async def execute(self):
            return [True, 1]

    transactions = []
    monkeypatch.setattr(cache, "redis", SimpleNamespace(pipeline=lambda transaction: transactions.append(transaction) or Pipe()))

    assert asyncio.run(cache.incr_with_ttl("k", 30)) == 1
    assert transactions == [True]
    assert calls == [("set", "k", 0, 30, True), ("incr", "k")]
