"""issue #97: /tagall экранирует текст, ограничен кулдауном и переживает flood wait."""
import asyncio
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import CommandObject
from aiogram.methods import SendMessage

from bot.handlers.chat import tag_settings as ts
from bot.utils.i18n import t


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(ts, "_sleep", fake_sleep)
    return sleeps


def _members(monkeypatch, user_ids):
    async def fake_load(chat_id):
        return list(user_ids)

    monkeypatch.setattr(ts, "load_member_ids", fake_load)


def _message():
    sent: list[str] = []

    async def answer(text, **kwargs):
        sent.append(text)

    return SimpleNamespace(chat=SimpleNamespace(id=-100), answer=answer), sent


async def _call(message, args=None):
    await ts.tag_all(message, CommandObject(prefix="/", command="tagall", args=args), lang="ru")
    if ts._tasks:
        await asyncio.gather(*ts._tasks)


def _retry_after(seconds: int) -> TelegramRetryAfter:
    return TelegramRetryAfter(method=SendMessage(chat_id=-100, text="x"), message="Flood", retry_after=seconds)


def test_build_note_escapes_html():
    assert ts.build_note("<b>&") == "&lt;b&gt;&amp;"
    assert ts.build_note(None) == ts.DEFAULT_NOTE


def test_tagall_sends_escaped_note_in_batches(monkeypatch):
    _members(monkeypatch, range(1, 8))
    message, sent = _message()

    asyncio.run(_call(message, "<b>&"))

    assert len(sent) == 2
    assert all(text.startswith("&lt;b&gt;&amp; ") for text in sent)
    assert "<b>" not in sent[0]


def test_second_call_during_broadcast_is_rejected(monkeypatch):
    _members(monkeypatch, [1, 2])
    message, sent = _message()

    async def run():
        await _call(message)
        await _call(message)

    asyncio.run(run())

    assert sent[-1] == t("ru", "tagall_busy", minutes=ts.COOLDOWN_SEC // 60)
    assert len(sent) == 2


def test_empty_chat_releases_cooldown(monkeypatch, fake_redis):
    _members(monkeypatch, [])
    message, sent = _message()

    asyncio.run(_call(message))

    assert sent == [t("ru", "tagall_empty")]
    assert fake_redis.data.get(ts.cooldown_key(-100)) is None


def test_flood_wait_is_retried(no_sleep):
    sent: list[str] = []
    errors = [_retry_after(3)]

    async def send(text):
        if errors:
            raise errors.pop()
        sent.append(text)

    count = asyncio.run(ts.send_mentions(send, "hi", [1, 2, 3, 4, 5, 6]))

    assert count == 2 and len(sent) == 2
    assert 3 in no_sleep


def test_other_telegram_error_stops_broadcast():
    calls: list[str] = []

    async def send(text):
        calls.append(text)
        raise TelegramBadRequest(method=SendMessage(chat_id=-100, text="x"), message="chat not found")

    assert asyncio.run(ts.send_mentions(send, "hi", list(range(20)))) == 0
    assert len(calls) == 1
