"""Тесты для issue #11: редактор прав и custom-роли реально влияют на доступ к командам,
а повышение/понижение в Telegram сразу сбрасывает кэш роли."""
import asyncio
from types import SimpleNamespace

import pytest
from aiogram.types import (
    ChatMemberAdministrator, ChatMemberBanned, ChatMemberMember, ChatMemberOwner,
)

from bot.filters import roles as role_filter
from bot.services import roles
from bot.utils.permissions import can_run_command, command_name


@pytest.mark.parametrize("text, expected", [
    ("/ban", "ban"), ("/Ban@DSRobot причина", "ban"), ("/mute 1h", "mute"),
    ("hello", None), (None, None), ("/", None),
])
def test_command_name(text, expected):
    assert command_name(text) == expected


def test_default_minimum_role_is_used_without_override():
    assert can_run_command("admin", "admin", command="ban")
    assert can_run_command("developer", "owner", command="promote")
    assert not can_run_command("member", "admin", command="ban")


def test_command_permission_override_is_applied():
    assert can_run_command("member", "admin", command="warn", override="member")
    assert not can_run_command("admin", "admin", command="ban", override="owner")


def test_locked_commands_ignore_override():
    assert not can_run_command("member", "owner", command="setcmdperm", override="member")
    assert not can_run_command("admin", "owner", command="promote", override="admin")


def test_unknown_or_developer_override_is_ignored():
    assert can_run_command("owner", "admin", command="ban", override="developer")
    assert can_run_command("admin", "admin", command="ban", override="nonsense")


def test_custom_role_permissions_grant_matching_commands_only():
    perms = {"ban", "mute"}
    assert can_run_command("custom", "admin", command="ban", custom_permissions=perms)
    assert can_run_command("custom", "admin", command="mute", custom_permissions=perms)
    assert not can_run_command("custom", "admin", command="kick", custom_permissions=perms)
    assert not can_run_command("custom", "admin", command="setwarnlimit", custom_permissions=perms)
    # Права действуют только у роли custom.
    assert not can_run_command("member", "admin", command="ban", custom_permissions=perms)


def _event(text: str):
    return SimpleNamespace(text=text, chat=SimpleNamespace(id=-100, type="supergroup"))


def test_has_role_filter_uses_command_permissions(monkeypatch):
    async def overrides(chat_id):
        return {"warn": "member"}

    monkeypatch.setattr(role_filter, "get_command_min_roles", overrides)
    f = role_filter.HasRole("admin")

    assert asyncio.run(f(_event("/warn"), chat_user_role="member"))
    assert not asyncio.run(f(_event("/ban"), chat_user_role="member"))
    assert asyncio.run(f(_event("/ban"), chat_user_role="custom", chat_user_permissions=frozenset({"ban"})))


def _user(uid=7):
    return SimpleNamespace(id=uid, is_bot=False, first_name="T")


def test_role_from_member_and_stored_role():
    user = _user()
    owner = ChatMemberOwner.model_construct(status="creator", user=user, is_anonymous=False)
    admin = ChatMemberAdministrator.model_construct(status="administrator", user=user)
    member = ChatMemberMember.model_construct(status="member", user=user)
    banned = ChatMemberBanned.model_construct(status="kicked", user=user, until_date=0)

    assert roles.role_from_member(owner) == "owner"
    assert roles.role_from_member(admin) == "admin"
    assert roles.role_from_member(member) == "member"
    # Разжалованный админ с custom-ролью сохраняет custom-роль.
    assert roles.stored_role(member, custom_role_id=5) == "custom"
    assert roles.stored_role(member, custom_role_id=None) == "member"
    assert roles.stored_role(banned, custom_role_id=5) == "banned"


class FakeBot:
    def __init__(self, member):
        self.member = member
        self.calls = 0

    async def get_chat_member(self, chat_id, user_id):
        self.calls += 1
        return self.member


@pytest.fixture
def cache(monkeypatch):
    store: dict = {}

    async def get_json(key):
        return store.get(key)

    async def set_json(key, value, ex=None):
        store[key] = value

    monkeypatch.setattr(roles, "get_json", get_json)
    monkeypatch.setattr(roles, "set_json", set_json)
    return store


def test_developer_ids_get_developer_role(monkeypatch, cache):
    monkeypatch.setattr(roles.settings, "developer_user_ids", "7, 8")
    bot = FakeBot(None)
    access = asyncio.run(roles.resolve_access(bot, -100, 7))
    assert access.role == "developer"
    assert bot.calls == 0


def test_custom_role_is_resolved_and_cached(monkeypatch, cache):
    monkeypatch.setattr(roles.settings, "developer_user_ids", "")

    async def custom_access(chat_id, user_id):
        return roles.Access("custom", frozenset({"ban"}))

    monkeypatch.setattr(roles, "_custom_access", custom_access)
    bot = FakeBot(ChatMemberMember.model_construct(status="member", user=_user()))

    first = asyncio.run(roles.resolve_access(bot, -100, 7))
    second = asyncio.run(roles.resolve_access(bot, -100, 7))

    assert first == second == roles.Access("custom", frozenset({"ban"}))
    assert bot.calls == 1  # второй раз — из кэша


def test_telegram_admin_skips_custom_lookup(monkeypatch, cache):
    monkeypatch.setattr(roles.settings, "developer_user_ids", "")

    async def custom_access(chat_id, user_id):
        raise AssertionError("не должно вызываться для админа")

    monkeypatch.setattr(roles, "_custom_access", custom_access)
    bot = FakeBot(ChatMemberAdministrator.model_construct(status="administrator", user=_user()))
    assert asyncio.run(roles.resolve_access(bot, -100, 7)).role == "admin"


def test_legacy_string_cache_is_still_understood(monkeypatch, cache):
    monkeypatch.setattr(roles.settings, "developer_user_ids", "")
    cache[roles.role_cache_key(-100, 7)] = "admin"
    bot = FakeBot(None)
    assert asyncio.run(roles.resolve_access(bot, -100, 7)).role == "admin"
    assert bot.calls == 0
