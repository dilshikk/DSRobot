"""issue #44: посты привязанного канала в группе обсуждений не модерируются."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram.types import Chat, Message, User

from bot.middlewares import chat_context, moderation_pipeline as mp

CHANNEL = -1001
GROUP = -100


def _msg(sender_chat=None, auto=None):
    return Message.model_construct(
        message_id=1, date=datetime.now(), chat=Chat.model_construct(id=GROUP, type="supergroup"),
        from_user=User.model_construct(id=777000, is_bot=False, first_name="Telegram"), text="https://post.link",
        sender_chat=sender_chat, is_automatic_forward=auto,
    )


@pytest.fixture
def bot(monkeypatch):
    cache = {}

    async def get_json(key):
        return cache.get(key)

    async def set_json(key, value, ex=None):
        cache[key] = value

    monkeypatch.setattr(chat_context, "get_json", get_json)
    monkeypatch.setattr(chat_context, "set_json", set_json)
    calls = []

    async def get_chat(chat_id):
        calls.append(chat_id)
        return SimpleNamespace(linked_chat_id=CHANNEL)

    return SimpleNamespace(get_chat=get_chat, calls=calls)


def _linked(bot, message):
    return asyncio.run(chat_context.is_linked_channel_post(bot, message))


def test_automatic_forward_is_linked(bot):
    assert _linked(bot, _msg(Chat.model_construct(id=CHANNEL, type="channel"), auto=True))
    assert bot.calls == []


def test_post_as_linked_channel(bot):
    assert _linked(bot, _msg(Chat.model_construct(id=CHANNEL, type="channel")))
    assert _linked(bot, _msg(Chat.model_construct(id=CHANNEL, type="channel")))
    assert bot.calls == [GROUP]  # второй раз — из кэша


@pytest.mark.parametrize("sender", [
    None,
    Chat.model_construct(id=-1002, type="channel"),   # чужой канал — модерируется, как раньше
    Chat.model_construct(id=GROUP, type="supergroup"),  # анонимный админ — своя ветка
])
def test_other_senders_are_not_linked(bot, sender):
    assert not _linked(bot, _msg(sender))


def test_pipeline_skips_linked_channel(monkeypatch):
    called = []

    async def check(message, settings, role):
        called.append(True)
        return True

    monkeypatch.setattr(mp, "MESSAGE_CHECKS", [check])

    async def handler(event, data):
        return "handled"

    data = {"chat_settings": {}, "chat_user_role": "member", "is_linked_channel": True}
    assert asyncio.run(mp.ModerationPipelineMiddleware()(handler, _msg(auto=True), data)) == "handled"
    assert called == []
    data["is_linked_channel"] = False
    assert asyncio.run(mp.ModerationPipelineMiddleware()(handler, _msg(), data)) is None
    assert called == [True]
