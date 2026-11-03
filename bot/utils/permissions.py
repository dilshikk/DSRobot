"""Иерархия ролей и проверка прав. Roles and permissions hierarchy + Custom roles."""
from __future__ import annotations

from enum import IntEnum


class Role(IntEnum):
    member = 0
    approved = 1
    custom = 2
    admin = 3
    owner = 4
    developer = 5  # владелец инфраструктуры бота (глобальный супер-админ)


ROLE_ORDER = {r.name: r.value for r in Role}


def role_at_least(role: str, minimum: str) -> bool:
    return ROLE_ORDER.get(role, 0) >= ROLE_ORDER.get(minimum, 0)


# Права, которые может выдавать custom-роль (используются в редакторе ролей / permissions_editor)
CUSTOM_ROLE_PERMISSIONS = [
    "ban", "unban", "mute", "unmute", "kick", "warn", "unwarn",
    "pin", "unpin", "delete_messages", "change_settings", "invite_users",
    "manage_topics", "post_recurring", "view_stats",
]
