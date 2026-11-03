"""issue #39: капча не должна оставлять участника ограниченным навсегда."""
import asyncio
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import ChatMemberMember, ChatPermissions, User

from bot.handlers.welcome import captcha

CHAT_DEFAULT = ChatPermissions(can_send_messages=True)
USERS = [User(id=5, is_bot=False, first_name="A"), User(id=6, is_bot=False, first_name="B")]


class FakeBot:
    id = 1

    def __init__(self, send_fails=False):
        self.send_fails = send_fails
        self.restricts: list[tuple[int, bool]] = []

    async def get_chat(self, chat_id):
        return SimpleNamespace(permissions=CHAT_DEFAULT)

    async def get_chat_member(self, chat_id, user_id):
        return ChatMemberMember(user=USERS[0])

    async def restrict_chat_member(self, chat_id, user_id, permissions, until_date=None):
        self.restricts.append((user_id, permissions.can_send_messages))

    async def send_message(self, chat_id, text, **kwargs):
        if self.send_fails:
            raise TelegramBadRequest(method=SendMessage(chat_id=chat_id, text=text),
                                     message="Bad Request: not enough rights to send text messages")
        return SimpleNamespace(message_id=10)


@pytest.fixture
def env(monkeypatch):
    calls = {"state": {}, "jobs": [], "kicks": [], "deleted": [], "settings": []}

    async def set_json(key, value, ex=None):
        calls["state"][key] = value

    async def get_json(key):
        return calls["state"].get(key)

    async def redis_delete(*keys):
        calls["deleted"].extend(keys)

    async def noop(*args, **kwargs):
        return None

    async def apply_sanction(bot, chat_id, user_id, action, *args, **kwargs):
        calls["kicks"].append(user_id)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def update_settings(session, chat_id, section, values):
        calls["settings"].append((section, values))

    async def get_chat_lang(chat_id):
        return "ru"

    monkeypatch.setattr(captcha, "set_json", set_json)
    monkeypatch.setattr(captcha, "get_json", get_json)
    monkeypatch.setattr(captcha, "redis", SimpleNamespace(set=noop, delete=redis_delete, ttl=lambda k: asyncio.sleep(0, 60)))
    monkeypatch.setattr(captcha, "schedule_once", lambda *a, **k: calls["jobs"].append(k))
    monkeypatch.setattr(captcha, "_cleanup", noop)
    monkeypatch.setattr(captcha, "apply_sanction", apply_sanction)
    monkeypatch.setattr(captcha, "SessionFactory", FakeSession)
    monkeypatch.setattr(captcha, "update_settings", update_settings)
    monkeypatch.setattr(captcha, "get_chat_lang", get_chat_lang)
    return calls


def _settings(kick=True):
    return {"captcha": {"mode": "math", "kick_on_fail": kick}}


def test_send_failure_rolls_back_restriction_for_every_member(env):
    bot = FakeBot(send_fails=True)

    started = asyncio.run(captcha.start_captcha(bot, -100, _settings(), USERS))

    assert started == []
    assert bot.restricts == [(5, False), (5, True), (6, False), (6, True)]
    assert env["jobs"] == []
    assert captcha._state_key(-100, 5) in env["deleted"]


def test_timeout_without_kick_lifts_restriction(env, monkeypatch):
    bot = FakeBot()
    monkeypatch.setattr(captcha, "get_bot", lambda bot_id: bot)
    asyncio.run(captcha.start_captcha(bot, -100, _settings(kick=False), USERS[:1]))

    asyncio.run(captcha.captcha_timeout(-100, 5, kick=False, bot_id=1))

    assert bot.restricts[-1] == (5, True)
    assert env["kicks"] == []


def _press(bot, env, value):
    answers = []
    callback = SimpleNamespace(
        message=SimpleNamespace(chat=SimpleNamespace(id=-100)), data=f"cap:5:{value}",
        from_user=USERS[0], bot=bot,
        answer=lambda text=None, **k: asyncio.sleep(0, answers.append(text)),
    )
    asyncio.run(captcha.check_captcha_answer(callback))
    return answers[-1]


@pytest.mark.parametrize("kick", [True, False])
def test_exhausted_attempts_respect_kick_on_fail(env, kick):
    bot = FakeBot()
    asyncio.run(captcha.start_captcha(bot, -100, _settings(kick=kick), USERS[:1]))
    wrong = env["state"][captcha._state_key(-100, 5)]["answer"] + 100

    for _ in range(captcha.MAX_ATTEMPTS):
        _press(bot, env, wrong)

    assert env["kicks"] == ([5] if kick else [])
    if not kick:
        right = env["state"][captcha._state_key(-100, 5)]["answer"]
        assert "закончились" in _press(bot, env, right)  # после исчерпания попыток ответ не принимается
        assert bot.restricts[-1] == (5, False)


@pytest.mark.parametrize("args, saved", [("60", {"timeout_sec": 60}), ("3600", {"timeout_sec": 3600})])
def test_captchatimeout_saves(env, args, saved):
    message = SimpleNamespace(chat=SimpleNamespace(id=-100), answer=lambda *a, **k: asyncio.sleep(0))
    asyncio.run(captcha.set_captcha_timeout(message, SimpleNamespace(args=args)))
    assert env["settings"] == [("captcha", saved)]


@pytest.mark.parametrize("args", [None, "abc", "5", "99999", "-1"])
def test_captchatimeout_rejects_bad_input(env, args):
    message = SimpleNamespace(chat=SimpleNamespace(id=-100), answer=lambda *a, **k: asyncio.sleep(0))
    asyncio.run(captcha.set_captcha_timeout(message, SimpleNamespace(args=args)))
    assert env["settings"] == []


@pytest.mark.parametrize("args, value", [("on", True), ("OFF", False), ("maybe", None)])
def test_captchakick(env, args, value):
    message = SimpleNamespace(chat=SimpleNamespace(id=-100), answer=lambda *a, **k: asyncio.sleep(0))
    asyncio.run(captcha.set_captcha_kick(message, SimpleNamespace(args=args)))
    assert env["settings"] == ([] if value is None else [("captcha", {"kick_on_fail": value})])
