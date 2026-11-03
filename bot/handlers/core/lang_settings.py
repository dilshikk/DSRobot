"""Langs and lang settings: /setlang меняет язык ответов бота в чате (issue #12)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.chat_lang import remember_chat_lang
from bot.services.settings_service import get_or_create_chat
from bot.utils.i18n import AVAILABLE_LANGS, t

router = Router(name="lang_settings")


@router.message(Command("setlang"), HasRole("admin"))
async def set_lang(message: Message, command: CommandObject, lang: str = "ru") -> None:
    new_lang = (command.args or "").strip().lower()
    if new_lang not in AVAILABLE_LANGS:
        await message.answer(t(lang, "lang_usage", langs=", ".join(AVAILABLE_LANGS)))
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        chat.lang = new_lang
        await session.commit()
    # Капча и фоновые задачи читают язык из кэша — обновляем его сразу.
    await remember_chat_lang(message.chat.id, new_lang)
    # Подтверждение — уже на новом языке.
    await message.answer(t(new_lang, "lang_changed"))
