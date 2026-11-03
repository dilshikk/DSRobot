"""issue #43: настройки, которые сохранялись, но не работали или не выключались."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram.types import Chat, Message, MessageEntity, User

from bot.database.models import ChatSettings
from bot.handlers.chat import admin_tag, privacy
from bot.handlers.misc import alphabets
from bot.handlers.moderation import banned_words, blocks, media_blocks, message_deletion
from bot.handlers.welcome import goodbye, welcome
from bot.middlewares.moderation_pipeline import MESSAGE_CHECKS
from bot.services.moderation_actions import parse_auto_action

DEFAULT_KEYS = set(ChatSettings.DEFAULTS)


def _msg(text="hi", entities=None, **extra):
    return Message.model_construct(
        message_id=1, date=datetime.now(), chat=Chat.model_construct(id=-100, type="supergroup"),
        from_user=User.model_construct(id=42, is_bot=False, first_name="T"), text=text, entities=entities, **extra,
    )


@pytest.fixture
def saved(monkeypatch):
    calls = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def update_settings(session, chat_id, section, values):
        calls.append((section, values))

    for module in (banned_words, media_blocks, alphabets, message_deletion, welcome, goodbye, admin_tag):
        monkeypatch.setattr(module, "SessionFactory", FakeSession)
        monkeypatch.setattr(module, "update_settings", update_settings)
    return calls


def saved_session(calls):
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False
    return FakeSession


def saved_update(calls):
    async def update_settings(session, chat_id, section, values):
        calls.append((section, values))
    return update_settings


def _run(handler, args=None):
    answers = []
    message = SimpleNamespace(chat=SimpleNamespace(id=-100), answer=lambda text, **k: asyncio.sleep(0, answers.append(text)))
    if args is None:
        asyncio.run(handler(message))
    else:
        asyncio.run(handler(message, SimpleNamespace(args=args)))
    return answers


@pytest.fixture
def deleted(monkeypatch):
    calls = []

    async def fake_delete(message, notify=True):
        calls.append(message)
        return True

    monkeypatch.setattr(blocks, "delete_message_safely", fake_delete)
    return calls


@pytest.mark.parametrize("key, message", [
    ("links", _msg("go https://spam.ru")),
    ("links", _msg("spam.ru", [MessageEntity(type="url", offset=0, length=7)])),
    ("usernames", _msg("@spam", [MessageEntity(type="mention", offset=0, length=5)])),
    ("inline", _msg("gif", via_bot=User.model_construct(id=7, is_bot=True, first_name="gif"))),
])
def test_content_blocks_delete(deleted, key, message):
    settings = {"blocks": {key: True}}
    assert asyncio.run(blocks.check_content_blocks(message, settings, "member")) is True
    assert asyncio.run(blocks.check_content_blocks(message, {"blocks": {key: False}}, "member")) is False
    assert asyncio.run(blocks.check_content_blocks(message, settings, "admin")) is False


def test_content_blocks_ignore_plain_text(deleted):
    settings = {"blocks": {"links": True, "usernames": True, "inline": True}}
    assert asyncio.run(blocks.check_content_blocks(_msg("hello"), settings, "member")) is False
    assert not deleted


def test_content_blocks_in_pipeline():
    assert blocks.check_content_blocks in MESSAGE_CHECKS


def test_dead_settings_removed():
    assert not {"privacy", "tag_all", "topics"} & DEFAULT_KEYS
    assert not hasattr(privacy, "toggle_privacy_mode")


@pytest.mark.parametrize("args, parsed", [
    ("mute", {"action": "mute", "mute_minutes": 60}), ("mute 5", {"action": "mute", "mute_minutes": 5}),
    ("kick", {"action": "kick"}), ("ban 5", None), ("mute 0", None), ("off", None), ("", None),
])
def test_wordaction(saved, args, parsed):
    assert parse_auto_action(args, banned_words.WORD_ACTIONS) == parsed
    _run(banned_words.set_word_action, args)
    assert saved == ([] if parsed is None else [("banned_words", parsed)])


def test_block_and_blockmedia_reply(saved, monkeypatch):
    # t(lang, key, key=...) падал с TypeError: /block и /blockmedia никогда не отвечали.
    monkeypatch.setattr(blocks, "SessionFactory", saved_session(saved))
    monkeypatch.setattr(blocks, "update_settings", saved_update(saved))
    assert "photo" in _run(media_blocks.block_media, "photo")[0]
    assert "links" in _run(blocks.block_toggle, "links")[0]
    assert "links" in _run(blocks.unblock_toggle, "links")[0]
    assert saved == [("media_blocks", {"photo": True}), ("blocks", {"links": True}), ("blocks", {"links": False})]


def test_unblockmedia(saved):
    _run(media_blocks.unblock_media, "photo")
    _run(media_blocks.unblock_media, "nope")
    assert saved == [("media_blocks", {"photo": False})]


def test_setalphabet_off(saved):
    _run(alphabets.set_alphabet, "off")
    assert saved == [("alphabets", {"enabled": False})]


@pytest.mark.parametrize("args, value", [("30", 30), ("0", 0), ("-1", None), ("x", None), ("86401", None)])
def test_delcommands(saved, args, value):
    _run(message_deletion.set_command_autodelete, args)
    assert saved == ([] if value is None else [("message_deletion", {"delete_commands_after_sec": value})])


@pytest.mark.parametrize("args, value", [("on", True), ("off", False), ("", None)])
def test_welcomeclean(saved, args, value):
    _run(welcome.set_welcome_clean, args)
    assert saved == ([] if value is None else [("welcome", {"clean_old": value})])


def test_goodbyeoff(saved):
    _run(goodbye.goodbye_off)
    assert saved == [("goodbye", {"enabled": False})]


@pytest.mark.parametrize("args, value", [("60", 60), ("0", None), ("abc", None)])
def test_admincooldown(saved, args, value):
    _run(admin_tag.set_admin_cooldown, args)
    assert saved == ([] if value is None else [("tag_admin", {"cooldown_sec": value})])
