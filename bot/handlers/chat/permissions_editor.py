"""General commands permissions editor: минимальная роль для вызова произвольной команды.
Ответы — на языке чата (issue #12)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import CommandPermission
from bot.filters.roles import HasRole
from bot.services.roles import invalidate_command_permissions
from bot.utils.i18n import t
from bot.utils.permissions import ASSIGNABLE_MIN_ROLES, LOCKED_COMMANDS

router = Router(name="permissions_editor")


def setcmdperm_usage(lang: str) -> str:
    # Раньше подсказка была «/setcmdperm <команда> <member|...>» и ломала HTML-разметку.
    return t(lang, "setcmdperm_usage", roles=" | ".join(ASSIGNABLE_MIN_ROLES))


@router.message(Command("setcmdperm"), HasRole("owner"))
async def set_cmd_perm(message: Message, command: CommandObject, lang: str = "ru") -> None:
    """Использование: /setcmdperm КОМАНДА РОЛЬ"""
    parts = (command.args or "").split()
    if len(parts) != 2 or parts[1].lower() not in ASSIGNABLE_MIN_ROLES:
        await message.answer(setcmdperm_usage(lang))
        return
    cmd_name, role = parts[0].lstrip("/").lower(), parts[1].lower()
    if cmd_name in LOCKED_COMMANDS:
        await message.answer(t(lang, "setcmdperm_locked", command=cmd_name))
        return
    async with SessionFactory() as session:
        existing = (await session.execute(select(CommandPermission).where(
            CommandPermission.chat_id == message.chat.id, CommandPermission.command == cmd_name
        ))).scalar_one_or_none()
        if existing:
            existing.min_role = role
        else:
            session.add(CommandPermission(chat_id=message.chat.id, command=cmd_name, min_role=role))
        await session.commit()
    await invalidate_command_permissions(message.chat.id)
    await message.answer(t(lang, "setcmdperm_done", command=cmd_name, role=role))
