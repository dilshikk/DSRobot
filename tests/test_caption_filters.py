"""issue #40: подписи медиа и не текстовые сообщения не должны обходить фильтры."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram.types import Chat, Message, MessageEntity, PhotoSize, User, Voice

from bot.handlers.misc import alphabets
from bot.handlers.moderation import approve_mode, link_settings, masked_users, max_message_length, media_blocks, night_mode
from bot.middlewares import moderation_pipeline as mp

PHOTO = [PhotoSize(file_id="p", file_unique_id="p", width=1, height=1)]
VOICE = Voice(file_id="v", file_unique_id="v", duration=1)


def _msg(**fields) -> Message:
    return Message.model_construct(
        message_id=1, date=datetime.now(), chat=Chat.model_construct(id=-100, type="supergroup", title="t"),
        from_user=User.model_construct(id=42, is_bot=False, first_name="T"), **fields,
    )


@pytest.fixture
def deleted(monkeypatch):
    calls = []

    async def fake_delete(message, notify=True):
        calls.append(message.message_id)
        return True

    for module in (alphabets, approve_mode, link_settings, masked_users, max_message_length, media_blocks, night_mode):
        monkeypatch.setattr(module, "delete_message_safely", fake_delete)
    return calls


def _check(fn, message, settings):
    return asyncio.run(fn(message, settings, "member"))


def test_link_in_caption_is_deleted(deleted):
    assert _check(link_settings.check_links, _msg(photo=PHOTO, caption="go https://spam.example"),
                  {"link_settings": {"action": "delete"}})
    assert deleted


def test_long_caption_is_deleted(deleted):
    assert _check(max_message_length.check_max_length, _msg(photo=PHOTO, caption="x" * 20),
                  {"max_message_length": {"enabled": True, "limit": 10}})


def test_alphabet_checks_caption(deleted):
    assert _check(alphabets.check_alphabet, _msg(photo=PHOTO, caption="Привет мир"),
                  {"alphabets": {"enabled": True, "allowed": ["latin"]}}) is True


def test_masked_link_in_caption_entities(deleted):
    caption = "😀 safe.com"
    entity = MessageEntity(type="text_link", offset=3, length=8, url="https://evil.example/x")
    assert _check(masked_users.check_masked_links, _msg(photo=PHOTO, caption=caption, caption_entities=[entity]),
                  {"blocks": {"masked_links": True}})


def test_honest_link_after_emoji_is_kept(deleted):
    # offset в UTF-16: эмодзи занимает 2 единицы, видимый текст совпадает с доменом ссылки.
    entity = MessageEntity(type="text_link", offset=3, length=8, url="https://safe.com/page")
    assert not _check(masked_users.check_masked_links, _msg(text="😀 safe.com", entities=[entity]),
                      {"blocks": {"masked_links": True}})


@pytest.mark.parametrize("kind, fields", [
    ("video_note", {"video_note": object()}), ("audio", {"audio": object()}), ("poll", {"poll": object()}),
    ("contact", {"contact": object()}), ("location", {"location": object()}), ("location", {"venue": object()}),
])
def test_new_media_blocks(deleted, kind, fields):
    assert _check(media_blocks.check_media_block, _msg(**fields), {"media_blocks": {kind: True}})


class FakeSession:
    """Возвращает участника, который вступил при включённом approve mode и ждёт одобрения (issue #50)."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        pending = SimpleNamespace(pending_approval=True, approved=False)
        return SimpleNamespace(scalar_one_or_none=lambda: pending)


def test_night_mode_deletes_voice(deleted, monkeypatch):
    hour = datetime.utcnow().hour
    settings = {"utc_offset": 0, "night_mode": {"enabled": True, "start_hour": hour, "end_hour": (hour + 1) % 24}}
    assert _check(night_mode.check_night_mode, _msg(voice=VOICE), settings)


def test_approve_mode_deletes_voice_from_unapproved(deleted, monkeypatch):
    notified = []

    async def fake_notify(message):
        notified.append(message.message_id)

    monkeypatch.setattr(approve_mode, "SessionFactory", FakeSession)
    # У сообщения из model_construct нет бота, поэтому уведомление подменяем.
    monkeypatch.setattr(approve_mode, "_notify_pending", fake_notify)
    assert _check(approve_mode.check_unapproved, _msg(voice=VOICE), {"approve_mode": {"enabled": True}})
    assert deleted == [1] and notified == [1]


@pytest.mark.parametrize("fields, service", [
    ({"text": "hi"}, False), ({"voice": VOICE}, False), ({"photo": PHOTO, "caption": "c"}, False),
    ({"new_chat_title": "x"}, True), ({"left_chat_member": object()}, True),
])
def test_is_service(fields, service):
    assert mp._is_service(_msg(**fields)) is service
