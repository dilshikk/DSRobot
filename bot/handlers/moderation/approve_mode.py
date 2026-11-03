"""Approve mode: сообщения новых участников фильтруются, пока их не одобрит админ."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import ChatUser
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings

router = Router(name="approve_mode")


@router.message(Command("approve"), HasRole("admin"))
async def approve_user(message: Message) -> None:
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя: /approve")
        return
    target_id = message.reply_to_message.from_user.id
    async with SessionFactory() as session:
        cu = (await session.execute(
            select(ChatUser).where(ChatUser.chat_id == message.chat.id, ChatUser.user_id == target_id)
        )).scalar_one_or_none()
        if cu is None:
            cu = ChatUser(chat_id=message.chat.id, user_id=target_id)
            session.add(cu)
        cu.approved = True
        await session.commit()
    await message.answer("\u2705 Пользователь одобрен.")


@router.message(Command("approvemode"), HasRole("admin"))
async def toggle_approve_mode(message: Message, chat_settings: dict) -> None:
    new_state = not chat_settings.get("approve_mode", {}).get("enabled", False)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "approve_mode", {"enabled": new_state})
    await message.answer(f"Approve mode: {'включён' if new_state else 'выключен'}")


@router.message(F.text | F.photo | F.video | F.sticker, ~F.text.startswith("/"))
async def gate_unapproved(message: Message, chat_settings: dict, chat_user_role: str = "member") -> None:
    if not chat_settings.get("approve_mode", {}).get("enabled") or chat_user_role in ("admin", "owner", "developer"):
        return
    async with SessionFactory() as session:
        cu = (await session.execute(
            select(ChatUser).where(ChatUser.chat_id == message.chat.id, ChatUser.user_id == message.from_user.id)
        )).scalar_one_or_none()
    if not cu or not cu.approved:
        try:
            await message.delete()
        except Exception:
            pass
