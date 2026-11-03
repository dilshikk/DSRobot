"""issue #45: команды отвечают пользователю, а не падают с исключением."""
import asyncio
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import PromoteChatMember

from bot.handlers.chat import admin_tag, checks_settings, personal_commands, staff_group
from bot.handlers.core import errors
from bot.handlers.welcome import rules
from bot.utils.parsing import parse_chat_id, parse_int


@pytest.mark.parametrize("raw, value", [
    ("+5", 5), ("-12", -12), ("14", 14), ("--5", None), ("+-5", None), ("15", None), ("", None), ("5a", None),
    ("9" * 30, None),
])
def test_parse_int(raw, value):
    assert parse_int(raw, -12, 14) == value


@pytest.mark.parametrize("raw, value", [("-1001234567890", -1001234567890), ("--100", None), ("-", None)])
def test_parse_chat_id(raw, value):
    assert parse_chat_id(raw) == value


class FakeSession:
    def __init__(self, existing=None):
        self.existing, self.added, self.commits = existing, [], 0

    async def execute(self, stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: self.existing)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1


def test_save_trigger_inserts_new():
    session = FakeSession()
    assert asyncio.run(personal_commands.save_trigger(session, -1, "#hi", "text", "hello", 1)) is False
    assert len(session.added) == 1 and session.commits == 1


def test_save_trigger_replaces_duplicate():
    row = SimpleNamespace(response_type="sticker", response_content="old", created_by=2)
    session = FakeSession(row)
    assert asyncio.run(personal_commands.save_trigger(session, -1, "#hi", "text", "new", 1)) is True
    assert session.added == [] and (row.response_type, row.response_content, row.created_by) == ("text", "new", 1)


@pytest.mark.parametrize("module", [rules, admin_tag, checks_settings, staff_group])
def test_group_only_routers(module):
    filters = [f.callback for f in module.router.message._handler.filters or []]
    assert filters, f"{module.__name__}: нет фильтра типа чата"


def test_telegram_error_is_answered(monkeypatch):
    answers = []

    async def chat_lang(chat_id):
        return "en"

    monkeypatch.setattr(errors, "get_chat_lang", chat_lang)
    message = SimpleNamespace(chat=SimpleNamespace(id=-1),
                              answer=lambda text, **k: asyncio.sleep(0, answers.append(text)))
    exc = TelegramBadRequest(PromoteChatMember(chat_id=-1, user_id=1), "Bad Request: not enough rights")
    event = SimpleNamespace(update=SimpleNamespace(update_id=1, message=message), exception=exc)
    assert asyncio.run(errors.on_telegram_error(event)) is True
    assert "not enough rights" in answers[0]
