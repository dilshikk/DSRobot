"""issue #41: whitelist по домену, проверка всех ссылок, мут по ссылкам на срок."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram.types import Chat, Message, MessageEntity, User

from bot.handlers.moderation import banned_words, link_settings as ls

WL = {"link_settings": {"action": "delete", "whitelist": ["google.com"]}}


def _msg(text, entities=None):
    return Message.model_construct(
        message_id=1, date=datetime.now(), chat=Chat.model_construct(id=-100, type="supergroup"),
        from_user=User.model_construct(id=42, is_bot=False, first_name="T"), text=text, entities=entities,
    )


@pytest.fixture
def env(monkeypatch):
    calls = {"deleted": 0, "sanctions": [], "settings": []}

    async def fake_delete(message, notify=True):
        calls["deleted"] += 1
        return True

    async def fake_sanction(bot, chat_id, user_id, action, reason="", actor=0, duration=None, lang="ru"):
        calls["sanctions"].append((action, duration, lang))

    async def chat_lang(chat_id):
        return "en"

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def update_settings(session, chat_id, section, values):
        calls["settings"].append(values)

    monkeypatch.setattr(ls, "delete_message_safely", fake_delete)
    for module in (ls, banned_words):
        monkeypatch.setattr(module, "apply_sanction", fake_sanction)
        monkeypatch.setattr(module, "get_chat_lang", chat_lang)
    monkeypatch.setattr(ls, "SessionFactory", FakeSession)
    monkeypatch.setattr(ls, "update_settings", update_settings)
    return calls


def _check(message, settings=WL):
    return asyncio.run(ls.check_links(message, settings, "member"))


@pytest.mark.parametrize("text", [
    "https://google.com.evil.ru", "https://evil.ru/?google.com", "https://notgoogle.com",
    "https://google.com ok https://spam.ru",
])
def test_whitelist_bypasses_are_blocked(env, text):
    assert _check(_msg(text)) is True


@pytest.mark.parametrize("text", ["https://google.com/search?q=1", "see https://mail.google.com", "www.Google.com"])
def test_whitelisted_links_pass(env, text):
    assert _check(_msg(text)) is False


def test_bare_domain_entity_is_checked(env):
    entity = MessageEntity(type="url", offset=4, length=7)
    assert _check(_msg("😀😀spam.ru", [entity])) is True  # offset в UTF-16


def test_text_link_entity_is_checked(env):
    entity = MessageEntity(type="text_link", offset=0, length=6, url="https://spam.ru")
    assert _check(_msg("google", [entity])) is True


def test_no_links_pass(env):
    assert _check(_msg("hello file.txt")) is False


def test_link_mute_has_duration_and_lang(env):
    _check(_msg("https://spam.ru"), {"link_settings": {"action": "mute", "mute_minutes": 15}})
    assert env["sanctions"] == [("mute", 15, "en")]


def test_banned_word_mute_has_duration(env, monkeypatch):
    async def words(chat_id):
        return ["spam"]

    async def fake_delete(self, *args, **kwargs):
        return True

    monkeypatch.setattr(Message, "delete", fake_delete)
    monkeypatch.setattr(banned_words, "get_banned_words", words)
    monkeypatch.setattr(banned_words, "find_banned", lambda *a: True)
    asyncio.run(banned_words.check_banned_words(_msg("spam"), {"banned_words": {"action": "mute"}}, "member"))
    assert env["sanctions"] == [("mute", 60, "en")]


@pytest.mark.parametrize("raw, host", [
    ("HTTPS://www.Google.com:443/x", "google.com"), ("t.me/chan", "t.me"), ("google.com.", "google.com"),
])
def test_link_host(raw, host):
    assert ls.link_host(raw) == host


def _cmd(fn, args, settings=None):
    answers = []
    message = SimpleNamespace(chat=SimpleNamespace(id=-100), answer=lambda text, **k: asyncio.sleep(0, answers.append(text)))
    if settings is None:
        asyncio.run(fn(message, SimpleNamespace(args=args)))
    else:
        asyncio.run(fn(message, SimpleNamespace(args=args), settings))
    return answers


def test_denylink_removes_domain(env):
    _cmd(ls.remove_whitelisted_domain, "https://Google.com/", {"link_settings": {"whitelist": ["google.com", "x.org"]}})
    assert env["settings"] == [{"whitelist": ["x.org"]}]


def test_allowlink_normalizes(env):
    _cmd(ls.whitelist_domain, "https://www.Google.com/path", {"link_settings": {"whitelist": []}})
    assert env["settings"] == [{"whitelist": ["google.com"]}]


@pytest.mark.parametrize("args, saved", [
    ("on", {"allow_admins": True}), ("off", {"allow_admins": False}), ("x", None),
])
def test_linkadmins(env, args, saved):
    _cmd(ls.set_allow_admins, args)
    assert env["settings"] == ([] if saved is None else [saved])


@pytest.mark.parametrize("args, saved", [
    ("mute 30", {"action": "mute", "mute_minutes": 30}), ("ban", {"action": "ban"}),
    ("ban 5", None), ("mute 0", None), ("nope", None),
])
def test_linkaction(env, args, saved):
    _cmd(ls.set_link_action, args)
    assert env["settings"] == ([] if saved is None else [saved])
