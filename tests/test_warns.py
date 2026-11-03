"""issue #37: варны обнуляются после лимитного действия, мут по лимиту — на срок."""
import asyncio
from types import SimpleNamespace

import pytest

from bot.handlers.moderation import warns


class FakeMessage:
    def __init__(self):
        self.chat = SimpleNamespace(id=-100)
        self.answers: list[str] = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)


@pytest.fixture
def env(monkeypatch):
    calls = {"sanctions": [], "reset": [], "settings": []}
    target = SimpleNamespace(user_id=42, mention="@bob")

    async def prepare_target(message, args, usage, lang="ru"):
        return target, "spam"

    async def run_sanction(message, target, action, reason="", duration_minutes=None, lang="ru"):
        calls["sanctions"].append((action, duration_minutes))
        return True

    async def get_warns(chat_id, user_id):
        return calls.get("warns_count", 3)

    async def reset_warns(chat_id, user_id):
        calls["reset"].append(user_id)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def update_settings(session, chat_id, section, values):
        calls["settings"].append((section, values))

    monkeypatch.setattr(warns, "prepare_target", prepare_target)
    monkeypatch.setattr(warns, "run_sanction", run_sanction)
    monkeypatch.setattr(warns, "_get_warns", get_warns)
    monkeypatch.setattr(warns, "_reset_warns", reset_warns)
    monkeypatch.setattr(warns, "SessionFactory", FakeSession)
    monkeypatch.setattr(warns, "update_settings", update_settings)
    return calls


def _warn(settings, calls, count=3):
    calls["warns_count"] = count
    message = FakeMessage()
    asyncio.run(warns.cmd_warn(message, SimpleNamespace(args="spam"), settings))
    return message


def test_limit_resets_warns(env):
    _warn({"warns": {"max_warns": 3, "action": "kick"}}, env)

    assert env["sanctions"] == [("warn", None), ("kick", None)]
    assert env["reset"] == [42]


def test_limit_mute_has_duration(env):
    _warn({"warns": {"max_warns": 3, "action": "mute", "mute_minutes": 15}}, env)
    assert env["sanctions"][-1] == ("mute", 15)

    env["sanctions"].clear()
    _warn({"warns": {"max_warns": 3, "action": "mute"}}, env)
    assert env["sanctions"][-1] == ("mute", warns.DEFAULT_MUTE_MINUTES)


def test_below_limit_does_not_reset(env):
    _warn({"warns": {"max_warns": 3}}, env, count=2)

    assert env["sanctions"] == [("warn", None)]
    assert env["reset"] == []


@pytest.mark.parametrize("args, expected", [
    ("ban", {"action": "ban"}),
    ("mute 30", {"action": "mute", "mute_minutes": 30}),
    ("MUTE", {"action": "mute", "mute_minutes": warns.DEFAULT_MUTE_MINUTES}),
])
def test_setwarnaction_saves(env, args, expected):
    asyncio.run(warns.set_warn_action(FakeMessage(), SimpleNamespace(args=args)))
    assert env["settings"] == [("warns", expected)]


@pytest.mark.parametrize("args", [None, "", "delete", "ban 10", "mute 0", "mute -5", "mute abc", "mute 999999999"])
def test_setwarnaction_rejects_bad_input(env, args):
    message = FakeMessage()
    asyncio.run(warns.set_warn_action(message, SimpleNamespace(args=args)))
    assert env["settings"] == []
    assert "/setwarnaction" in message.answers[0]
