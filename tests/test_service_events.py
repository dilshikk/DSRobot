"""Регрессионные тесты для issue #1: при вступлении в чат выполняются все шаги
(блок ботов → капча → приветствие → статистика → удаление), а не только первый."""
import asyncio
from types import SimpleNamespace

import pytest

from bot.handlers.welcome import service_events as se


def _user(uid: int, is_bot: bool = False):
    return SimpleNamespace(id=uid, is_bot=is_bot)


@pytest.fixture
def calls(monkeypatch):
    log: list[tuple] = []

    async def kick_blocked_bots(bot, chat_id, settings, members):
        log.append(("blocks", [m.id for m in members]))
        return [m for m in members if m.id != 999]  # 999 — заблокированный бот

    async def start_captcha(bot, chat_id, settings, humans):
        log.append(("captcha", [m.id for m in humans]))
        return [2]  # пользователь 2 получил капчу

    async def greet_members(bot, chat_id, settings, members):
        log.append(("welcome", [m.id for m in members]))

    async def bump_stat(chat_id, field):
        log.append(("stats", field))

    async def delete_service_message(message, settings):
        log.append(("cleanup",))

    for name, fn in {
        "kick_blocked_bots": kick_blocked_bots,
        "start_captcha": start_captcha,
        "greet_members": greet_members,
        "bump_stat": bump_stat,
        "delete_service_message": delete_service_message,
    }.items():
        monkeypatch.setattr(se, name, fn)
    return log


def _join_message(*members):
    return SimpleNamespace(bot=object(), chat=SimpleNamespace(id=-100), new_chat_members=list(members))


def test_join_runs_every_step_in_order(calls):
    msg = _join_message(_user(1), _user(2), _user(999, is_bot=True))

    asyncio.run(se.on_members_joined(msg, chat_settings={}))

    assert [c[0] for c in calls] == ["blocks", "captcha", "welcome", "stats", "cleanup"]
    assert ("captcha", [1, 2]) in calls
    # пользователь на капче приветствуется позже, после её прохождения
    assert ("welcome", [1]) in calls
    assert ("stats", "joins_count") in calls


def test_failing_step_does_not_cancel_the_rest(calls, monkeypatch):
    async def broken_captcha(*args):
        calls.append(("captcha",))
        raise RuntimeError("no rights")

    monkeypatch.setattr(se, "start_captcha", broken_captcha)
    msg = _join_message(_user(1))

    asyncio.run(se.on_members_joined(msg, chat_settings={}))

    assert [c[0] for c in calls] == ["blocks", "captcha", "welcome", "stats", "cleanup"]
    assert ("welcome", [1]) in calls


def test_only_service_events_router_handles_new_members():
    """Ни один другой роутер не должен снова перехватывать new_chat_members."""
    from bot.handlers import ALL_ROUTERS

    offenders = []
    for router in ALL_ROUTERS:
        if router is se.router:
            continue
        for h in router.message.handlers:
            if "new_chat_members" in repr([f.callback for f in h.filters or []]):
                offenders.append(f"{router.name}.{h.callback.__name__}")
    assert offenders == []
