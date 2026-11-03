"""Custom roles: именованные наборы прав (не полноценный admin Telegram, а внутренняя роль бота).
Ответы — на языке чата (issue #12)."""
from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import ChatUser, CustomRole
from bot.filters.roles import HasRole
from bot.services.roles import invalidate_role
from bot.services.user_service import ensure_chat_user, upsert_tg_user
from bot.utils.i18n import t
from bot.utils.permissions import CUSTOM_ROLE_PERMISSIONS

router = Router(name="custom_roles")


def role_created_text(lang: str, name: str, perms: list[str]) -> str:
    return t(lang, "addrole_done", name=escape(name), perms=", ".join(perms) or "\u2014")


@router.message(Command("addrole"), HasRole("admin"))
async def add_role(message: Message, command: CommandObject, lang: str = "ru") -> None:
    """Использование: /addrole <name> <perm1,perm2,...>"""
    if not command.args or " " not in command.args:
        await message.answer(t(lang, "addrole_usage", perms=", ".join(CUSTOM_ROLE_PERMISSIONS)))
        return
    name, perms_raw = command.args.split(maxsplit=1)
    perms = {p.strip(): True for p in perms_raw.split(",") if p.strip() in CUSTOM_ROLE_PERMISSIONS}
    async with SessionFactory() as session:
        exists = (await session.execute(
            select(CustomRole.id).where(CustomRole.chat_id == message.chat.id, CustomRole.name == name)
        )).first()
        if exists:
            await message.answer(t(lang, "role_exists", name=escape(name)))
            return
        session.add(CustomRole(chat_id=message.chat.id, name=name, permissions=perms))
        await session.commit()
    await message.answer(role_created_text(lang, name, list(perms)))


@router.message(Command("setrole"), HasRole("admin"))
async def set_role(message: Message, command: CommandObject, lang: str = "ru") -> None:
    """Ответом на сообщение: /setrole <role_name>"""
    reply = message.reply_to_message
    if not reply or not reply.from_user or not command.args:
        await message.answer(t(lang, "setrole_usage"))
        return
    role_name = command.args.strip()
    target = reply.from_user
    async with SessionFactory() as session:
        role = (await session.execute(
            select(CustomRole).where(CustomRole.chat_id == message.chat.id, CustomRole.name == role_name)
            .order_by(CustomRole.id)
        )).scalars().first()  # дубли имён могли остаться с прошлых версий
        if not role:
            await message.answer(t(lang, "role_not_found"))
            return
        # users-строка должна существовать раньше chat_users (FK, см. issue #4).
        await upsert_tg_user(session, target)
        cu: ChatUser = await ensure_chat_user(session, message.chat.id, target.id)
        cu.role = "custom"
        cu.custom_role_id = role.id
        await session.commit()
    # Новая роль действует сразу, а не после истечения кэша.
    await invalidate_role(message.chat.id, target.id)
    await message.answer(t(lang, "setrole_done", name=escape(role_name)))
