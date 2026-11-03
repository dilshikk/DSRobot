"""Goodbye: сообщение при выходе участника."""
from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, User

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


async def farewell(bot: Bot, chat_id: int, chat_settings: dict, member: User | None) -> None:
    """Вызывается из service_events при выходе участника."""
    cfg = chat_settings.get("goodbye", {})
    if member is None or not cfg.get("enabled"):
        return
    await bot.send_message(
        chat_id,
        cfg.get("text", "{mention} покинул(а) чат.").format(mention=member.mention_html()),
        parse_mode="HTML",
    )
