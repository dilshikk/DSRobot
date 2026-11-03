"""Langs and lang settings."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import get_or_create_chat

router = Router(name="lang_settings")

AVAILABLE_LANGS = ["ru", "en"]


@router.message(Command("setlang"), HasRole("admin"))
async def set_lang(message: Message, command: CommandObject) -> None:
    lang = (command.args or "").strip().lower()
    if lang not in AVAILABLE_LANGS:
        await message.answer(f"Доступные языки: {', '.join(AVAILABLE_LANGS)}")
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        chat.lang = lang
        await session.commit()
    await message.answer(f"\u2705 Язык чата изменён на: {lang}")
