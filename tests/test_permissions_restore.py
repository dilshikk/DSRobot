"""issue #38: /unmute и капча возвращают права чата, а капча не снимает прежний мут."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetChat
from aiogram.types import ChatMemberMember, ChatMemberRestricted, ChatPermissions, User

from bot.handlers.welcome import captcha
from bot.services import moderation_actions as ma

CHAT_DEFAULT = ChatPermissions(can_send_messages=True, can_send_polls=False, can_send_voice_notes=True)
USER = User(id=5, is_bot=False, first_name="Bob")


def _restricted(until: datetime | None) -> ChatMemberRestricted:
    flags = {name: False for name in ChatPermissions.model_fields}
    flags["can_send_messages"] = True  # частичное ограничение: текст можно, медиа нельзя
    return ChatMemberRestricted(user=USER, is_member=True, until_date=until or 0, **flags)


class FakeBot:
    id = 1

    def __init__(self, member=None, chat_error=False):
        self.member = member or ChatMemberMember(user=USER)
        self.chat_error = chat_error
        self.restricts: list[tuple[ChatPermissions, datetime | None]] = []

    async def get_chat(self, chat_id):
        if self.chat_error:
            raise TelegramBadRequest(method=GetChat(chat_id=chat_id), message="Bad Request: chat not found")
        return SimpleNamespace(permissions=CHAT_DEFAULT)

    async def get_chat_member(self, chat_id, user_id):
        return self.member

    async def restrict_chat_member(self, chat_id, user_id, permissions, until_date=None):
        self.restricts.append((permissions, until_date))

    async def send_message(self, *args, **kwargs):
        return SimpleNamespace(message_id=10)


def test_unmute_restores_chat_default_permissions():
    bot = FakeBot()
    assert asyncio.run(ma._call_telegram(bot, -100, 5, "unmute", None, "ru")) is None
    assert bot.restricts == [(CHAT_DEFAULT, None)]


def test_unmute_fallback_includes_all_media():
    bot = FakeBot(chat_error=True)
    asyncio.run(ma._call_telegram(bot, -100, 5, "unmute", None, "ru"))
    permissions = bot.restricts[0][0]
    for name in ("can_send_voice_notes", "can_send_video_notes", "can_send_polls", "can_add_web_page_previews"):
        assert getattr(permissions, name) is True, name


@pytest.fixture
def captcha_env(monkeypatch):
    saved = {}

    async def set_json(key, value, ex=None):
        saved["state"] = value

    async def get_json(key):
        return saved.get("state")

    async def noop(*args, **kwargs):
        return None

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def get_settings(session, chat_id):
        return {}

    monkeypatch.setattr(captcha, "set_json", set_json)
    monkeypatch.setattr(captcha, "get_json", get_json)
    monkeypatch.setattr(captcha, "redis", SimpleNamespace(set=noop))
    monkeypatch.setattr(captcha, "schedule_once", lambda *a, **k: None)
    monkeypatch.setattr(captcha, "_cleanup", noop)
    monkeypatch.setattr(captcha, "SessionFactory", FakeSession)
    monkeypatch.setattr(captcha, "get_settings", get_settings)
    monkeypatch.setattr(captcha, "greet_members", noop)
    return saved


def _pass_captcha(bot, saved):
    asyncio.run(captcha.start_captcha(bot, -100, {"captcha": {"mode": "math"}}, [USER]))
    callback = SimpleNamespace(
        message=SimpleNamespace(chat=SimpleNamespace(id=-100)),
        data=f"cap:{USER.id}:{saved['state']['answer']}",
        from_user=USER, bot=bot, answer=lambda *a, **k: asyncio.sleep(0),
    )
    asyncio.run(captcha.check_captcha_answer(callback))
    return bot.restricts[-1]


def test_captcha_pass_gives_chat_default_permissions(captcha_env):
    bot = FakeBot()
    assert _pass_captcha(bot, captcha_env) == (CHAT_DEFAULT, None)
    assert "restore" not in captcha_env["state"]


def test_rejoined_muted_user_keeps_mute_after_captcha(captcha_env):
    until = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=2)
    bot = FakeBot(member=_restricted(until))

    permissions, restored_until = _pass_captcha(bot, captcha_env)

    assert restored_until == until
    assert permissions.can_send_messages is True and permissions.can_send_photos is False


def test_forever_restriction_is_restored_without_until(captcha_env):
    bot = FakeBot(member=_restricted(None))
    permissions, restored_until = _pass_captcha(bot, captcha_env)
    assert restored_until is None and permissions.can_send_photos is False


def test_expired_restriction_is_ignored(captcha_env):
    bot = FakeBot(member=_restricted(datetime.now(timezone.utc) - timedelta(minutes=1)))
    assert _pass_captcha(bot, captcha_env) == (CHAT_DEFAULT, None)
