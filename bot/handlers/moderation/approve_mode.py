"""Approve mode: сообщения новых участников фильтруются, пока их не одобрит админ.
Проверка вызывается из moderation_pipeline. Ответы — на языке чата (issue #12)."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import ChatUser
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings
from bot.utils.i18n import t, toggle_text
from bot.utils.permissions import is_privileged
from bot.utils.telegram import delete_message_safely

router = Router(name="approve_mode")


@router.message(Command("approve"), HasRole("admin"))
async def approve_user(message: Message, lang: str = "ru") -> None:
    reply = message.reply_to_message
    if not reply or not reply.from_user:
        await message.answer(t(lang, "approve_usage"))
        return
    target_id = reply.from_user.id
    async with SessionFactory() as session:
        cu = (await session.execute(
            select(ChatUser).where(ChatUser.chat_id == message.chat.id, ChatUser.user_id == target_id)
        )).scalar_one_or_none()
        if cu is None:
            cu = ChatUser(chat_id=message.chat.id, user_id=target_id)
            session.add(cu)
        cu.approved = True
        await session.commit()
    await message.answer(t(lang, "approve_done"))


@router.message(Command("unapprove"), HasRole("admin"))
async def unapprove_user(message: Message, lang: str = "ru") -> None:
    reply = message.reply_to_message
    if not reply or not reply.from_user:
        await message.answer(t(lang, "unapprove_usage"))
        return
    async with SessionFactory() as session:
        cu = (await session.execute(
            select(ChatUser).where(ChatUser.chat_id == message.chat.id, ChatUser.user_id == reply.from_user.id)
        )).scalar_one_or_none()
        if cu is not None:
            cu.approved = False
            await session.commit()
    await message.answer(t(lang, "unapprove_done"))


@router.message(Command("approvemode"), HasRole("admin"))
async def toggle_approve_mode(message: Message, chat_settings: dict, lang: str = "ru") -> None:
    new_state = not chat_settings.get("approve_mode", {}).get("enabled", False)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "approve_mode", {"enabled": new_state})
    await message.answer(toggle_text(lang, "feature_approve_mode", new_state))


async def check_unapproved(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    if not chat_settings.get("approve_mode", {}).get("enabled") or is_privileged(chat_user_role):
        return False
    async with SessionFactory() as session:
        cu = (await session.execute(
            select(ChatUser).where(ChatUser.chat_id == message.chat.id, ChatUser.user_id == message.from_user.id)
        )).scalar_one_or_none()
    if cu and cu.approved:
        return False
    await delete_message_safely(message)
    return True
