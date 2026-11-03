"""Blocks settings: forwards / links / usernames-mentions / bots / inline-queries."""
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings

router = Router(name="blocks")

TOGGLES = {"forwards", "links", "usernames", "bots", "inline"}


@router.message(Command("block"), HasRole("admin"))
async def block_toggle(message: Message, command: CommandObject) -> None:
    key = (command.args or "").strip().lower()
    if key not in TOGGLES:
        await message.answer(f"Использование: /block <{'|'.join(TOGGLES)}>")
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "blocks", {key: True})
    await message.answer(f"\u2705 Блокировка «{key}» включена.")


@router.message(Command("unblock"), HasRole("admin"))
async def unblock_toggle(message: Message, command: CommandObject) -> None:
    key = (command.args or "").strip().lower()
    if key not in TOGGLES:
        await message.answer(f"Использование: /unblock <{'|'.join(TOGGLES)}>")
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "blocks", {key: False})
    await message.answer(f"\u2705 Блокировка «{key}» выключена.")


@router.message(F.forward_date | F.forward_from | F.forward_from_chat)
async def enforce_forward_block(message: Message, chat_settings: dict, chat_user_role: str = "member") -> None:
    if chat_settings.get("blocks", {}).get("forwards") and chat_user_role not in ("admin", "owner", "developer"):
        try:
            await message.delete()
        except Exception:
            pass


@router.message(F.new_chat_members)
async def enforce_bot_block(message: Message, chat_settings: dict) -> None:
    if not chat_settings.get("blocks", {}).get("bots"):
        return
    for member in message.new_chat_members:
        if member.is_bot:
            try:
                await message.chat.ban(member.id)
                await message.chat.unban(member.id)
            except Exception:
                pass
