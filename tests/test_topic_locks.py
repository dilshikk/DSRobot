"""issue #43: TopicSettings.locked_features раньше сохранялся, но нигде не проверялся."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram.types import Chat, Message, PhotoSize, User

from bot.handlers.chat import topics_settings
from bot.middlewares.moderation_pipeline import MESSAGE_CHECKS, SKIP_ON_COMMAND


def _msg(text=None, topic=True, **extra):
    return Message.model_construct(
        message_id=1, date=datetime.now(), chat=Chat.model_construct(id=-100, type="supergroup"),
        from_user=User.model_construct(id=42, is_bot=False, first_name="T"), text=text,
        message_thread_id=5 if topic else None, is_topic_message=topic, **extra,
    )


PHOTO = [PhotoSize.model_construct(file_id="x", file_unique_id="y", width=1, height=1)]


@pytest.fixture
def deleted(monkeypatch):
    calls = []

    async def fake_delete(message, notify=True):
        calls.append(message)
        return True

    monkeypatch.setattr(topics_settings, "delete_message_safely", fake_delete)
    return calls


@pytest.fixture
def locks(monkeypatch):
    current: list[str] = []

    async def fake_get(chat_id, topic_id):
        return current

    monkeypatch.setattr(topics_settings, "get_topic_locks", fake_get)
    return current


def _check(message, role="member"):
    return asyncio.run(topics_settings.check_topic_locks(message, {}, role))


def test_enabled_locks_filters_unknown_and_disabled():
    assert topics_settings.enabled_locks({"photo": True, "text": False, "nope": True}) == ["photo"]
    assert topics_settings.enabled_locks(None) == []


@pytest.mark.parametrize("kind, message", [
    ("text", _msg("hello")),
    ("links", _msg("go https://spam.ru")),
    ("photo", _msg(photo=PHOTO)),
])
def test_locked_content_is_deleted(deleted, locks, kind, message):
    locks.append(kind)
    assert _check(message) is True
    assert deleted == [message]


def test_unlocked_content_passes(deleted, locks):
    locks.append("photo")
    assert _check(_msg("hello")) is False
    assert not deleted


def test_admins_and_non_topic_messages_are_ignored(deleted, locks):
    locks.append("text")
    assert _check(_msg("hello"), role="admin") is False
    assert _check(_msg("hello", topic=False)) is False
    assert not deleted


def test_cached_locks_skip_database(monkeypatch, fake_redis):
    class NoSession:
        async def __aenter__(self):
            raise AssertionError("кэш должен отвечать без БД")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(topics_settings, "SessionFactory", NoSession)
    asyncio.run(fake_redis.set(topics_settings._locks_key(-100, 5), '["gif"]'))
    assert asyncio.run(topics_settings.get_topic_locks(-100, 5)) == ["gif"]


def test_lock_command_outside_topic(monkeypatch):
    answers = []
    message = SimpleNamespace(is_topic_message=False, message_thread_id=None,
                              answer=lambda text, **k: asyncio.sleep(0, answers.append(text)))
    asyncio.run(topics_settings.lock_topic_feature(message, SimpleNamespace(args="photo")))
    assert answers == [topics_settings.NOT_IN_TOPIC]


def test_lock_command_saves(monkeypatch):
    saved, answers = [], []

    async def fake_save(chat_id, topic_id, kind, locked):
        saved.append((chat_id, topic_id, kind, locked))
        return [kind] if locked else []

    monkeypatch.setattr(topics_settings, "save_topic_lock", fake_save)
    message = SimpleNamespace(chat=SimpleNamespace(id=-100), is_topic_message=True, message_thread_id=5,
                              answer=lambda text, **k: asyncio.sleep(0, answers.append(text)))
    asyncio.run(topics_settings.lock_topic_feature(message, SimpleNamespace(args="Photo")))
    asyncio.run(topics_settings.unlock_topic_feature(message, SimpleNamespace(args="photo")))
    asyncio.run(topics_settings.lock_topic_feature(message, SimpleNamespace(args="nope")))
    assert saved == [(-100, 5, "photo", True), (-100, 5, "photo", False)]
    assert answers[2].startswith("Использование")


def test_topic_locks_in_pipeline():
    assert topics_settings.check_topic_locks in MESSAGE_CHECKS
    assert topics_settings.check_topic_locks in SKIP_ON_COMMAND
