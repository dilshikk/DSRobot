"""Тесты для issue #10: отложенные задачи переживают перезапуск и выполняются нужным ботом."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from apscheduler.util import obj_to_ref, ref_to_obj

from bot.handlers.welcome import captcha
from bot.services import bot_registry, recurring
from bot.services.recurring import parse_recurring_args
from bot.services.scheduler import build_cron_trigger, remove_job, schedule_once, scheduler


@pytest.fixture(autouse=True)
def bots():
    bot_registry.clear()
    main, clone = SimpleNamespace(id=111), SimpleNamespace(id=222)
    bot_registry.register(main, main=True)
    bot_registry.register(clone)
    yield main, clone
    bot_registry.clear()


# --- задачи сохраняются в Redis как ссылка "модуль:функция" ---------------------------

@pytest.mark.parametrize("func", [captcha.captcha_timeout, recurring.send_recurring])
def test_job_functions_are_serializable_by_reference(func):
    assert ref_to_obj(obj_to_ref(func)) is func


def test_one_off_job_is_never_dropped_as_misfired():
    """Таймаут капчи должен выполниться даже после долгого простоя бота."""
    schedule_once(captcha.captcha_timeout, datetime.now(timezone.utc),
                  chat_id=-1, user_id=1, bot_id=111, job_id="test:once")
    try:
        job = scheduler.get_job("test:once")
        assert job is not None
        assert job.misfire_grace_time is None
        assert job.kwargs["bot_id"] == 111
    finally:
        remove_job("test:once")


# --- выбор бота ----------------------------------------------------------------------

def test_registry_falls_back_to_main_bot_for_legacy_jobs(bots):
    main, clone = bots
    assert bot_registry.get_bot(None) is main
    assert bot_registry.get_bot(222) is clone
    assert bot_registry.get_bot(999) is None


@pytest.fixture
def captcha_calls(monkeypatch):
    calls: list[tuple] = []
    state = {"value": {"answer": 5, "attempts": 0}}

    async def get_json(key):
        return state["value"]

    async def cleanup(bot, chat_id, user_id):
        calls.append(("cleanup", bot.id))

    async def apply_sanction(bot, chat_id, user_id, action, *args, **kwargs):
        calls.append((action, bot.id))

    monkeypatch.setattr(captcha, "get_json", get_json)
    monkeypatch.setattr(captcha, "_cleanup", cleanup)
    monkeypatch.setattr(captcha, "apply_sanction", apply_sanction)
    return calls, state


def test_captcha_timeout_kicks_with_the_bot_that_issued_it(captcha_calls):
    calls, _ = captcha_calls
    asyncio.run(captcha.captcha_timeout(-100, 7, kick=True, bot_id=222))
    assert calls == [("cleanup", 222), ("kick", 222)]


def test_captcha_timeout_skips_passed_captcha(captcha_calls):
    calls, state = captcha_calls
    state["value"] = None
    asyncio.run(captcha.captcha_timeout(-100, 7, kick=True, bot_id=222))
    assert calls == []


def test_captcha_timeout_does_nothing_when_bot_is_not_running(captcha_calls):
    calls, _ = captcha_calls
    asyncio.run(captcha.captcha_timeout(-100, 7, kick=True, bot_id=999))
    assert calls == []


def test_captcha_state_outlives_bot_downtime():
    assert captcha.STATE_GRACE_SEC >= 24 * 3600


# --- рассылки ------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ('"0 9 * * *" Доброе утро!', ("0 9 * * *", "Доброе утро!")),
    ("0 9 * * * Доброе утро!", ("0 9 * * *", "Доброе утро!")),
    ("\u00ab30 18 * * 1-5\u00bb Конец рабочего дня", ("30 18 * * 1-5", "Конец рабочего дня")),
    ("\u201c0 9 * * *\u201d Привет", ("0 9 * * *", "Привет")),
])
def test_parse_recurring_args_accepts_quoted_and_plain_cron(raw, expected):
    assert parse_recurring_args(raw) == expected


@pytest.mark.parametrize("raw", [
    None, "", '"0 9 * * *"', "0 9 * * *", '"0 9 * *" текст', '"99 9 * * *" текст', '"0 9 * * * текст',
])
def test_parse_recurring_args_rejects_invalid_input(raw):
    assert parse_recurring_args(raw) is None


def test_cron_uses_chat_utc_offset():
    """09:00 в чате с UTC+3 — это 06:00 UTC."""
    now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    fire = build_cron_trigger("0 9 * * *", utc_offset=3).get_next_fire_time(None, now)
    assert fire.astimezone(timezone.utc) == datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)


def test_cron_with_negative_offset():
    now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    fire = build_cron_trigger("0 9 * * *", utc_offset=-5).get_next_fire_time(None, now)
    assert fire.astimezone(timezone.utc) == datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)
