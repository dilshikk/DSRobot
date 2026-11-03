"""General commands permissions editor: минимальная роль для вызова произвольной команды."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import CommandPermission
from bot.filters.roles import HasRole
from bot.utils.permissions import ROLE_ORDER

router = Router(name="permissions_editor")


@router.message(Command("setcmdperm"), HasRole("owner"))
async def set_cmd_perm(message, command: CommandObject) -> None:
    """Использование: /setcmdperm <команда> <роль>"""
    parts = (command.args or "").split()
    if len(parts) != 2 or parts[1] not in ROLE_ORDER:
        await message.answer(f"Использование: /setcmdperm <команда> <{'|'.join(ROLE_ORDER)}>")
        return
    cmd_name, role = parts
    async with SessionFactory() as session:
        existing = (await session.execute(select(CommandPermission).where(
            CommandPermission.chat_id == message.chat.id, CommandPermission.command == cmd_name
        ))).scalar_one_or_none()
        if existing:
            existing.min_role = role
        else:
            session.add(CommandPermission(chat_id=message.chat.id, command=cmd_name, min_role=role))
        await session.commit()
    await message.answer(f"\u2705 /{cmd_name} теперь требует роль ≥ {role}")
