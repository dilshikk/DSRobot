"""issue #43: /delrole и /unsetrole — снять роль с участника и удалить роль целиком."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.handlers.moderation import custom_roles
from bot.utils.permissions import LOCKED_COMMANDS, can_run_command

LOCALES = Path(__file__).resolve().parent.parent / "bot" / "locales"
NEW_KEYS = ("delrole_usage", "delrole_done", "unsetrole_usage", "unsetrole_done", "unsetrole_none")


class NoSession:
    """Сессия не должна открываться, если ввод неверный."""

    async def __aenter__(self):
        raise AssertionError("БД не должна вызываться при неверном вводе")

    async def __aexit__(self, *exc):
        return False


def _message(reply=None):
    answers: list[str] = []

    async def answer(text, **kwargs):
        answers.append(text)

    return SimpleNamespace(chat=SimpleNamespace(id=-100), reply_to_message=reply, answer=answer), answers


@pytest.fixture(autouse=True)
def no_db(monkeypatch):
    monkeypatch.setattr(custom_roles, "SessionFactory", NoSession)


@pytest.mark.parametrize("args", [None, "", "   "])
def test_delrole_without_name_shows_usage(args):
    message, answers = _message()
    asyncio.run(custom_roles.del_role(message, SimpleNamespace(args=args), lang="en"))
    assert answers == [custom_roles.t("en", "delrole_usage")]


@pytest.mark.parametrize("reply", [
    None,
    SimpleNamespace(from_user=None, sender_chat=None),
    SimpleNamespace(from_user=SimpleNamespace(id=7), sender_chat=SimpleNamespace(id=-200)),
])
def test_unsetrole_needs_reply_to_user(reply):
    message, answers = _message(reply)
    asyncio.run(custom_roles.unset_role(message, lang="ru"))
    assert answers == [custom_roles.t("ru", "unsetrole_usage")]


def test_role_management_commands_are_locked():
    assert {"delrole", "unsetrole"} <= LOCKED_COMMANDS
    # /setcmdperm не может открыть их обычным участникам.
    assert not can_run_command("member", "admin", command="delrole", override="member")
    assert not can_run_command("member", "admin", command="unsetrole", override="member")


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_new_locale_keys_exist(lang):
    data = json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
    assert all(key in data for key in NEW_KEYS)
    assert "{name}" in data["delrole_done"] and "{count}" in data["delrole_done"]
