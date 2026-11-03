"""Goodbye: сообщение при выходе участника."""
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings

router = Router(name="goodbye")


@router.message(Command("setgoodbye"), HasRole("admin"))
async def set_goodbye(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Использование: /setgoodbye <текст с {mention}>")
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "goodbye", {"text": command.args, "enabled": True})
    await message.answer("\u2705 Прощание обновлено.")


@router.message(F.left_chat_member)
async def farewell(message: Message, chat_settings: dict) -> None:
    cfg = chat_settings.get("goodbye", {})
    if not cfg.get("enabled"):
        return
    member = message.left_chat_member
    await message.answer(cfg.get("text", "{mention} покинул(а) чат.").format(mention=member.mention_html()),
                          parse_mode="HTML")
