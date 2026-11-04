"""Custom roles: именованные наборы прав (не полноценный admin Telegram, а внутренняя роль бота).
Ответы — на языке чата (issue #12)."""
from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import delete, select, update

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


@router.message(Command("unsetrole"), HasRole("admin"))
async def unset_role(message: Message, lang: str = "ru") -> None:
    """Ответом на сообщение: /unsetrole — снять с участника custom-роль (issue #43)."""
    reply = message.reply_to_message
    if not reply or not reply.from_user or reply.sender_chat:
        await message.answer(t(lang, "unsetrole_usage"))
        return
    target = reply.from_user
    async with SessionFactory() as session:
        cu = (await session.execute(
            select(ChatUser).where(ChatUser.chat_id == message.chat.id, ChatUser.user_id == target.id)
        )).scalar_one_or_none()
        if cu is None or cu.custom_role_id is None:
            await message.answer(t(lang, "unsetrole_none"))
            return
        cu.custom_role_id = None
        if cu.role == "custom":
            cu.role = "member"
        await session.commit()
    await invalidate_role(message.chat.id, target.id)
    await message.answer(t(lang, "unsetrole_done"))


@router.message(Command("delrole"), HasRole("admin"))
async def del_role(message: Message, command: CommandObject, lang: str = "ru") -> None:
    """Использование: /delrole <name> — удалить роль и снять её со всех участников (issue #43)."""
    role_name = (command.args or "").strip()
    if not role_name:
        await message.answer(t(lang, "delrole_usage"))
        return
    chat_id = message.chat.id
    async with SessionFactory() as session:
        # Удаляем все роли с этим именем: дубли могли остаться с прошлых версий.
        role_ids = list((await session.execute(
            select(CustomRole.id).where(CustomRole.chat_id == chat_id, CustomRole.name == role_name)
        )).scalars())
        if not role_ids:
            await message.answer(t(lang, "role_not_found"))
            return
        holders = list((await session.execute(
            select(ChatUser.user_id).where(ChatUser.chat_id == chat_id, ChatUser.custom_role_id.in_(role_ids))
        )).scalars())
        # Сначала понижаем роль, потом чистим ссылку: иначе FK на custom_roles не даст удалить роль.
        await session.execute(
            update(ChatUser)
            .where(ChatUser.custom_role_id.in_(role_ids), ChatUser.role == "custom")
            .values(role="member")
        )
        await session.execute(
            update(ChatUser).where(ChatUser.custom_role_id.in_(role_ids)).values(custom_role_id=None)
        )
        await session.execute(delete(CustomRole).where(CustomRole.id.in_(role_ids)))
        await session.commit()
    # Права роли пропадают сразу, а не после истечения кэша.
    for user_id in holders:
        await invalidate_role(chat_id, user_id)
    await message.answer(t(lang, "delrole_done", name=escape(role_name), count=len(holders)))
