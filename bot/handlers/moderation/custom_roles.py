"""Custom roles: именованные наборы прав (не полноценный admin Telegram, а внутренняя роль бота)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import ChatUser, CustomRole
from bot.filters.roles import HasRole
from bot.utils.permissions import CUSTOM_ROLE_PERMISSIONS

router = Router(name="custom_roles")


@router.message(Command("addrole"), HasRole("admin"))
async def add_role(message, command: CommandObject) -> None:
    """Использование: /addrole <name> <perm1,perm2,...>"""
    if not command.args or " " not in command.args:
        await message.answer(f"Использование: /addrole <name> <{'|'.join(CUSTOM_ROLE_PERMISSIONS)}>")
        return
    name, perms_raw = command.args.split(maxsplit=1)
    perms = {p.strip(): True for p in perms_raw.split(",") if p.strip() in CUSTOM_ROLE_PERMISSIONS}
    async with SessionFactory() as session:
        session.add(CustomRole(chat_id=message.chat.id, name=name, permissions=perms))
        await session.commit()
    await message.answer(f"\u2705 Роль «{name}» создана с правами: {', '.join(perms) or '—'}")


@router.message(Command("setrole"), HasRole("admin"))
async def set_role(message, command: CommandObject) -> None:
    """Ответом на сообщение: /setrole <role_name>"""
    if not message.reply_to_message or not command.args:
        await message.answer("Ответьте на сообщение и укажите: /setrole <role_name>")
        return
    async with SessionFactory() as session:
        role = (await session.execute(
            select(CustomRole).where(CustomRole.chat_id == message.chat.id, CustomRole.name == command.args.strip())
        )).scalar_one_or_none()
        if not role:
            await message.answer("Роль с таким именем не найдена.")
            return
        target_id = message.reply_to_message.from_user.id
        cu = (await session.execute(
            select(ChatUser).where(ChatUser.chat_id == message.chat.id, ChatUser.user_id == target_id)
        )).scalar_one_or_none()
        if cu is None:
            cu = ChatUser(chat_id=message.chat.id, user_id=target_id)
            session.add(cu)
        cu.role = "custom"
        cu.custom_role_id = role.id
        await session.commit()
    await message.answer(f"\u2705 Пользователю назначена роль «{command.args.strip()}».")
