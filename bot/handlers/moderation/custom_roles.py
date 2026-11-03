"""Custom roles: именованные наборы прав (не полноценный admin Telegram, а внутренняя роль бота)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import ChatUser, CustomRole
from bot.filters.roles import HasRole
from bot.services.roles import invalidate_role
from bot.services.user_service import ensure_chat_user, upsert_tg_user
from bot.utils.permissions import CUSTOM_ROLE_PERMISSIONS

router = Router(name="custom_roles")


@router.message(Command("addrole"), HasRole("admin"))
async def add_role(message: Message, command: CommandObject) -> None:
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
async def set_role(message: Message, command: CommandObject) -> None:
    """Ответом на сообщение: /setrole <role_name>"""
    reply = message.reply_to_message
    if not reply or not reply.from_user or not command.args:
        await message.answer("Ответьте на сообщение и укажите: /setrole <role_name>")
        return
    role_name = command.args.strip()
    target = reply.from_user
    async with SessionFactory() as session:
        role = (await session.execute(
            select(CustomRole).where(CustomRole.chat_id == message.chat.id, CustomRole.name == role_name)
        )).scalar_one_or_none()
        if not role:
            await message.answer("Роль с таким именем не найдена.")
            return
        # users-строка должна существовать раньше chat_users (FK, см. issue #4).
        await upsert_tg_user(session, target)
        cu: ChatUser = await ensure_chat_user(session, message.chat.id, target.id)
        cu.role = "custom"
        cu.custom_role_id = role.id
        await session.commit()
    # Новая роль действует сразу, а не после истечения кэша.
    await invalidate_role(message.chat.id, target.id)
    await message.answer(f"\u2705 Пользователю назначена роль «{role_name}».")
