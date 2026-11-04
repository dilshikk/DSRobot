"""issue #14: антиспам — база CAS и правила для новичков. Сеть не нужна."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram.types import Chat, Message, MessageEntity, User

from bot.database.models import ChatSettings
from bot.handlers.moderation import link_settings, spam_guard
from bot.middlewares.moderation_pipeline import MESSAGE_CHECKS
from bot.services import cas

ON = {
    "antispam": {"enabled": True, "cas": True},
    "newcomers": {"action": "delete", "messages": 3, "hours": 24},
}
KEY = spam_guard.newcomer_key(-100, 42)


def _settings(**newcomers):
    return {**ON, "newcomers": {**ON["newcomers"], **newcomers}}


def _msg(text="hello", entities=None, user_id=42, username=None, edited=False):
    return Message.model_construct(
        message_id=1, date=datetime.now(), chat=Chat.model_construct(id=-100, type="supergroup"),
        from_user=User.model_construct(id=user_id, is_bot=False, first_name="S", username=username),
        sender_chat=None, text=text, entities=entities,
        edit_date=int(datetime.now().timestamp()) if edited else None,
    )


@pytest.fixture
def env(monkeypatch, fake_redis):
    state = SimpleNamespace(deleted=[], sanctions=[], fetched=[], cas_db=set(), redis=fake_redis)

    async def fake_delete(message, notify=True):
        state.deleted.append(message.message_id)
        return True

    async def fake_sanction(bot, chat_id, user_id, action, reason="", actor_user_id=0,
                            duration_minutes=None, lang="ru"):
        state.sanctions.append((user_id, action, duration_minutes))
        return None

    async def fake_fetch(user_id):
        state.fetched.append(user_id)
        return user_id in state.cas_db

    async def public_profile(bot, user):
        return bool(user.username)

    monkeypatch.setattr(spam_guard, "delete_message_safely", fake_delete)
    monkeypatch.setattr(spam_guard, "apply_sanction", fake_sanction)
    monkeypatch.setattr(spam_guard, "has_public_profile", public_profile)
    monkeypatch.setattr(cas, "fetch_cas_status", fake_fetch)
    return state


def _run(check, message, settings=ON, role="member"):
    return asyncio.run(check(message, settings, role))


def _join(user_id=42, settings=ON):
    asyncio.run(spam_guard.mark_newcomers(-100, settings, [SimpleNamespace(id=user_id, is_bot=False)]))


def _newcomer_check(message, settings=ON, role="member"):
    return _run(spam_guard.check_newcomer_spam, message, settings, role)


# --- CAS ---

def test_cas_listed_author_is_deleted_and_banned(env):
    env.cas_db.add(42)
    assert _run(spam_guard.check_cas, _msg()) is True
    assert env.deleted == [1]
    assert env.sanctions == [(42, "ban", None)]


def test_cas_result_is_cached(env):
    for _ in range(3):
        assert _run(spam_guard.check_cas, _msg()) is False
    assert env.fetched == [42]


def test_cas_outage_lets_messages_through_and_retries_later(env, monkeypatch):
    async def broken(user_id):
        env.fetched.append(user_id)
        return None

    monkeypatch.setattr(cas, "fetch_cas_status", broken)
    assert _run(spam_guard.check_cas, _msg()) is False
    assert _run(spam_guard.check_cas, _msg()) is False
    assert env.fetched == [42]
    assert 0 < asyncio.run(env.redis.ttl(cas.cas_cache_key(42))) <= cas.CAS_ERROR_TTL
    assert env.sanctions == []


@pytest.mark.parametrize("settings, role", [
    ({"antispam": {"enabled": True, "cas": False}}, "member"),
    ({"antispam": {"enabled": False, "cas": True}}, "member"),
    (ON, "admin"),
])
def test_cas_skipped_when_off_or_for_admins(env, settings, role):
    env.cas_db.add(42)
    assert _run(spam_guard.check_cas, _msg(), settings, role) is False
    assert env.fetched == []


def test_cas_listed_members_are_banned_on_join(env):
    env.cas_db.add(7)
    members = [SimpleNamespace(id=7, is_bot=False), SimpleNamespace(id=8, is_bot=False)]
    banned = asyncio.run(spam_guard.ban_cas_members(object(), -100, ON, members, lang="en"))
    assert banned == [7]
    assert env.sanctions == [(7, "ban", None)]


# --- новички ---

def test_old_member_is_not_checked_as_newcomer(env):
    assert _newcomer_check(_msg("https://spam.ru")) is False
    assert env.deleted == []


def test_newcomer_link_is_deleted(env):
    _join()
    assert _newcomer_check(_msg("buy here https://spam.ru")) is True
    assert env.deleted == [1]
    assert env.sanctions == []


def test_newcomer_whitelisted_link_passes(env):
    _join()
    settings = {**ON, "link_settings": {"whitelist": ["github.com"]}}
    assert _newcomer_check(_msg("see https://github.com/x"), settings) is False


def test_mention_is_spam_only_from_bare_profile(env):
    mention = [MessageEntity(type="mention", offset=0, length=5)]
    _join(42)
    _join(43)
    assert _newcomer_check(_msg("@shop", mention, user_id=42)) is True
    assert _newcomer_check(_msg("@shop", mention, user_id=43, username="real")) is False


def test_newcomer_becomes_trusted_after_clean_messages(env):
    _join()
    for _ in range(3):
        assert _newcomer_check(_msg("hi")) is False
    assert asyncio.run(env.redis.get(KEY)) is None
    assert _newcomer_check(_msg("https://spam.ru")) is False


def test_spam_does_not_earn_trust(env):
    _join()
    for _ in range(5):
        assert _newcomer_check(_msg("https://spam.ru")) is True
    assert asyncio.run(env.redis.get(KEY)) == "0"


def test_edit_is_checked_but_not_counted(env):
    _join()
    assert _newcomer_check(_msg("hi")) is False
    for _ in range(5):
        assert _newcomer_check(_msg("hi", edited=True)) is False
    assert asyncio.run(env.redis.get(KEY)) == "1"
    assert _newcomer_check(_msg("https://spam.ru", edited=True)) is True


def test_newcomer_mute_action(env):
    _join()
    assert _newcomer_check(_msg("https://spam.ru"), _settings(action="mute", mute_minutes=15)) is True
    assert env.sanctions == [(42, "mute", 15)]


@pytest.mark.parametrize("settings, role", [
    (_settings(action="off"), "member"),
    ({**ON, "antispam": {"enabled": False}}, "member"),
    (ON, "admin"),
])
def test_newcomer_check_skipped(env, settings, role):
    _join()
    assert _newcomer_check(_msg("https://spam.ru"), settings, role) is False


def test_newcomers_not_marked_when_off(env):
    _join(settings=_settings(action="off"))
    assert asyncio.run(env.redis.get(KEY)) is None


def test_newcomer_mark_expires(env):
    _join(settings=_settings(hours=2))
    assert 0 < asyncio.run(env.redis.ttl(KEY)) <= 2 * 3600


# --- команды и подключение ---

@pytest.fixture
def saved(monkeypatch):
    calls = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def update_settings(session, chat_id, section, values):
        calls.append((section, values))

    monkeypatch.setattr(spam_guard, "SessionFactory", FakeSession)
    monkeypatch.setattr(spam_guard, "update_settings", update_settings)
    return calls


def _command(handler, args):
    answers = []

    async def answer(text, **kwargs):
        answers.append(text)

    message = SimpleNamespace(chat=SimpleNamespace(id=-100), answer=answer)
    asyncio.run(handler(message, SimpleNamespace(args=args), lang="en"))
    return answers


@pytest.mark.parametrize("args, values", [
    ("mute 10", {"action": "mute", "mute_minutes": 10}), ("ban", {"action": "ban"}),
    ("off", {"action": "off"}), ("ban 5", None), ("nope", None), (None, None),
])
def test_newcomers_command(saved, args, values):
    answers = _command(spam_guard.set_newcomer_action, args)
    assert saved == ([] if values is None else [("newcomers", values)])
    assert len(answers) == 1


@pytest.mark.parametrize("args, value", [("on", True), ("OFF", False), ("maybe", None)])
def test_cas_command(saved, args, value):
    _command(spam_guard.toggle_cas, args)
    assert saved == ([] if value is None else [("antispam", {"cas": value})])


def test_checks_are_wired_into_pipeline():
    assert MESSAGE_CHECKS[0] is spam_guard.check_cas
    assert MESSAGE_CHECKS.index(spam_guard.check_newcomer_spam) < MESSAGE_CHECKS.index(link_settings.check_links)


def test_defaults_enable_new_protection():
    assert ChatSettings.DEFAULTS["antispam"]["cas"] is True
    assert ChatSettings.DEFAULTS["newcomers"]["action"] == "delete"
