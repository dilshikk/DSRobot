"""Тесты для issue #9: ошибки удаления не глушатся молча, админов предупреждают о нехватке прав."""
import asyncio
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage

from bot.utils import telegram as tg


def _bad_request(text: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=DeleteMessage(chat_id=-100, message_id=1), message=text)


class FakeRedis:
    def __init__(self):
        self.keys: set[str] = set()

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.keys:
            return None
        self.keys.add(key)
        return True


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


def _message(bot, error: Exception | None):
    async def delete():
        if error is not None:
            raise error

    return SimpleNamespace(bot=bot, chat=SimpleNamespace(id=-100), message_id=1, delete=delete)


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(tg, "redis", FakeRedis())
    return FakeBot()


def test_successful_delete_returns_true(bot):
    assert asyncio.run(tg.delete_message_safely(_message(bot, None))) is True
    assert bot.sent == []


def test_missing_rights_notifies_admins_once(bot, caplog):
    error = _bad_request("Bad Request: not enough rights to delete a message")
    assert asyncio.run(tg.delete_message_safely(_message(bot, error))) is False
    asyncio.run(tg.delete_message_safely(_message(bot, error)))
    assert len(bot.sent) == 1
    assert "не хватает прав" in bot.sent[0][1]
    assert "not enough rights" in caplog.text


def test_already_deleted_message_is_not_an_error(bot, caplog):
    error = _bad_request("Bad Request: message to delete not found")
    assert asyncio.run(tg.delete_message_safely(_message(bot, error))) is False
    assert bot.sent == []
    assert caplog.text == ""


def test_other_errors_are_logged_without_notice(bot, caplog):
    error = _bad_request("Bad Request: message can't be deleted for everyone")
    assert asyncio.run(tg.delete_message_safely(_message(bot, error))) is False
    assert bot.sent == []
    assert "can't be deleted" in caplog.text
