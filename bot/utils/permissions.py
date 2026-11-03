"""Иерархия ролей и проверка прав. Roles and permissions hierarchy + Custom roles."""
from __future__ import annotations

from collections.abc import Iterable
from enum import IntEnum


class Role(IntEnum):
    member = 0
    approved = 1
    custom = 2
    admin = 3
    owner = 4
    developer = 5  # владелец инфраструктуры бота (глобальный супер-админ), см. DEVELOPER_USER_IDS


ROLE_ORDER = {r.name: r.value for r in Role}

# Роли, которые можно указать в /setcmdperm. developer исключён: иначе владелец чата
# мог бы случайно запереть команду так, что сам не сможет её вызвать.
ASSIGNABLE_MIN_ROLES = tuple(name for name in ROLE_ORDER if name != "developer")


def role_at_least(role: str, minimum: str) -> bool:
    return ROLE_ORDER.get(role, 0) >= ROLE_ORDER.get(minimum, 0)


def is_privileged(role: str) -> bool:
    """admin/owner/developer — на них не распространяются авто-проверки модерации."""
    return role_at_least(role, "admin")


# Права, которые может выдавать custom-роль (используются в редакторе ролей / permissions_editor)
CUSTOM_ROLE_PERMISSIONS = [
    "ban", "unban", "mute", "unmute", "kick", "warn", "unwarn",
    "pin", "unpin", "delete_messages", "change_settings", "invite_users",
    "manage_topics", "post_recurring", "view_stats",
]

# Какое право custom-роли разрешает вызвать команду (issue #11).
COMMAND_PERMISSIONS: dict[str, str] = {
    "ban": "ban", "unban": "unban",
    "mute": "mute", "unmute": "unmute",
    "kick": "kick",
    "warn": "warn", "unwarn": "unwarn",
    "pin": "pin", "unpin": "unpin",
}

# Команды управления правами: их минимальную роль нельзя изменить через /setcmdperm,
# иначе можно выдать себе права на редактор прав.
LOCKED_COMMANDS = frozenset({"setcmdperm", "addrole", "setrole", "promote", "demote"})


def command_name(text: str | None) -> str | None:
    """'/Ban@MyBot причина' -> 'ban'. Для обычного текста возвращает None."""
    if not text or not text.startswith("/"):
        return None
    name = text.split(maxsplit=1)[0][1:].split("@", 1)[0].lower()
    return name or None


def can_run_command(
    role: str,
    minimum: str,
    *,
    command: str | None = None,
    custom_permissions: Iterable[str] = (),
    override: str | None = None,
) -> bool:
    """
    Решает, может ли роль вызвать команду (issue #11).

    - override — минимальная роль из редактора прав (/setcmdperm), заменяет значение
      по умолчанию из кода. Не действует для LOCKED_COMMANDS и не может быть developer.
    - custom-роль дополнительно проходит, если у неё есть право, связанное с командой
      (например, право "ban" разрешает /ban, даже если команда требует admin).
    """
    if command and command not in LOCKED_COMMANDS and override in ASSIGNABLE_MIN_ROLES:
        minimum = override
    if role_at_least(role, minimum):
        return True
    permission = COMMAND_PERMISSIONS.get(command or "")
    return role == "custom" and permission is not None and permission in set(custom_permissions)
