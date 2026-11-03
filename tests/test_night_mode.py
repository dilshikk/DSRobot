"""issue #42: одинаковые часы не закрывают чат на сутки, offset берётся из chat_settings."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from aiogram.types import Chat, Message, User

from bot.handlers.moderation import night_mode as nm


@pytest.mark.parametrize("hour, start, end, night", [
    (23, 22, 6, True), (3, 22, 6, True), (12, 22, 6, False),
    (10, 9, 18, True), (18, 9, 18, False),
    (5, 0, 0, False), (0, 7, 7, False),
])
def test_is_night(hour, start, end, night):
    assert nm.is_night(hour, start, end) is night


@pytest.mark.parametrize("args, parsed", [(["22", "6"], (22, 6)), (["0", "0"], None), (["7", "7"], None), (["24", "1"], None)])
def test_parse_hours(args, parsed):
    assert nm._parse_hours(args) == parsed


def test_check_uses_offset_from_settings_without_db(monkeypatch):
    deleted = []

    async def fake_delete(message, notify=True):
        deleted.append(message)
        return True

    def no_db():
        raise AssertionError("night mode не должен ходить в БД")

    monkeypatch.setattr(nm, "delete_message_safely", fake_delete)
    monkeypatch.setattr(nm, "SessionFactory", no_db)
    local_hour = (datetime.now(timezone.utc).hour + 5) % 24
    settings = {"utc_offset": 5, "night_mode": {"enabled": True, "start_hour": local_hour, "end_hour": (local_hour + 1) % 24}}
    message = Message.model_construct(message_id=1, date=datetime.now(), chat=Chat.model_construct(id=-100, type="supergroup"),
                                      from_user=User.model_construct(id=1, is_bot=False, first_name="A"), text="hi")

    assert asyncio.run(nm.check_night_mode(message, settings, "member")) is True
    assert deleted


def test_set_equal_hours_is_rejected(monkeypatch):
    answers = []
    monkeypatch.setattr(nm, "SessionFactory", lambda: (_ for _ in ()).throw(AssertionError("не сохранять")))
    message = SimpleNamespace(chat=SimpleNamespace(id=-100), answer=lambda text, **k: asyncio.sleep(0, answers.append(text)))
    asyncio.run(nm.set_night_mode(message, SimpleNamespace(args="0 0")))
    assert "/nightmode" in answers[0]
