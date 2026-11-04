"""Регрессионные тесты для issue #1: при вступлении в чат выполняются все шаги
(блок ботов → CAS → капча → приветствие → новички → статистика → удаление), а не только первый.
issue #12: язык чата доходит до капчи, приветствия и прощания.
issue #47: вышедший участник отмечается, статистика идёт по часовому поясу чата.
issue #14: аккаунты из базы CAS банятся без капчи и приветствия."""
import asyncio
from types import SimpleNamespace

import pytest

from bot.handlers.welcome import service_events as se

JOIN_STEPS = ["blocks", "cas", "captcha", "welcome", "newcomers", "stats", "cleanup"]


def _user(uid: int, is_bot: bool = False):
    return SimpleNamespace(id=uid, is_bot=is_bot)


@pytest.fixture
def calls(monkeypatch):
    log: list[tuple] = []

    async def kick_blocked_bots(bot, chat_id, settings, members):
        log.append(("blocks", [m.id for m in members]))
        return [m for m in members if m.id != 999]  # 999 — заблокированный бот

    async def ban_cas_members(bot, chat_id, settings, members, lang="ru"):
        log.append(("cas", [m.id for m in members]))
        return [3]  # пользователь 3 — в базе CAS

    async def start_captcha(bot, chat_id, settings, humans, lang="ru"):
        log.append(("captcha", [m.id for m in humans]))
        log.append(("captcha_lang", lang))
        return [2]  # пользователь 2 получил капчу

    async def greet_members(bot, chat_id, settings, members, lang="ru"):
        log.append(("welcome", [m.id for m in members]))
        log.append(("welcome_lang", lang))

    async def mark_newcomers(chat_id, settings, members):
        log.append(("newcomers", [m.id for m in members]))

    async def farewell(bot, chat_id, settings, member, lang="ru"):
        log.append(("goodbye", member.id))
        log.append(("goodbye_lang", lang))

    async def bump_stat(chat_id, field, utc_offset=0):
        log.append(("stats", field))
        log.append(("stats_offset", utc_offset))

    async def delete_service_message(message, settings):
        log.append(("cleanup",))

    async def forget_member(chat_id, user_id):
        log.append(("left", user_id))

    for name, fn in {
        "kick_blocked_bots": kick_blocked_bots,
        "ban_cas_members": ban_cas_members,
        "start_captcha": start_captcha,
        "greet_members": greet_members,
        "mark_newcomers": mark_newcomers,
        "farewell": farewell,
        "bump_stat": bump_stat,
        "delete_service_message": delete_service_message,
        "forget_member": forget_member,
    }.items():
        monkeypatch.setattr(se, name, fn)
    return log


def _steps(calls):
    return [c[0] for c in calls if not c[0].endswith(("_lang", "_offset"))]


def _join_message(*members):
    return SimpleNamespace(bot=object(), chat=SimpleNamespace(id=-100), new_chat_members=list(members))


def test_join_runs_every_step_in_order(calls):
    msg = _join_message(_user(1), _user(2), _user(999, is_bot=True))

    asyncio.run(se.on_members_joined(msg, chat_settings={}))

    assert _steps(calls) == JOIN_STEPS
    assert ("captcha", [1, 2]) in calls
    # пользователь на капче приветствуется позже, после её прохождения
    assert ("welcome", [1]) in calls
    assert ("newcomers", [1, 2]) in calls
    assert ("stats", "joins_count") in calls


def test_cas_listed_member_skips_captcha_welcome_and_newcomer_mark(calls):
    msg = _join_message(_user(1), _user(3))

    asyncio.run(se.on_members_joined(msg, chat_settings={}))

    assert ("cas", [1, 3]) in calls
    assert ("captcha", [1]) in calls
    assert ("welcome", [1]) in calls
    assert ("newcomers", [1]) in calls


def test_chat_language_reaches_captcha_and_welcome(calls):
    msg = _join_message(_user(1), _user(2))

    asyncio.run(se.on_members_joined(msg, chat_settings={}, lang="en"))

    assert ("captcha_lang", "en") in calls
    assert ("welcome_lang", "en") in calls


def test_chat_language_reaches_goodbye(calls):
    msg = SimpleNamespace(bot=object(), chat=SimpleNamespace(id=-100), left_chat_member=_user(5))

    asyncio.run(se.on_member_left(msg, chat_settings={}, lang="en"))

    assert ("goodbye_lang", "en") in calls


def test_leave_marks_member_left_and_counts(calls):
    msg = SimpleNamespace(bot=object(), chat=SimpleNamespace(id=-100), left_chat_member=_user(5))

    asyncio.run(se.on_member_left(msg, chat_settings={"utc_offset": 3}))

    assert _steps(calls) == ["goodbye", "left", "stats", "cleanup"]
    assert ("left", 5) in calls
    assert ("stats", "leaves_count") in calls
    assert ("stats_offset", 3) in calls


def test_failing_step_does_not_cancel_the_rest(calls, monkeypatch):
    async def broken_captcha(*args, **kwargs):
        calls.append(("captcha",))
        raise RuntimeError("no rights")

    monkeypatch.setattr(se, "start_captcha", broken_captcha)
    msg = _join_message(_user(1))

    asyncio.run(se.on_members_joined(msg, chat_settings={}))

    assert _steps(calls) == JOIN_STEPS
    assert ("welcome", [1]) in calls


def test_failing_cas_step_keeps_everyone(calls, monkeypatch):
    async def broken_cas(*args, **kwargs):
        calls.append(("cas",))
        raise RuntimeError("CAS down")

    monkeypatch.setattr(se, "ban_cas_members", broken_cas)
    asyncio.run(se.on_members_joined(_join_message(_user(1), _user(3)), chat_settings={}))

    assert ("captcha", [1, 3]) in calls


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
