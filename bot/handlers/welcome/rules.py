"""Rules. Ответы — на языке чата (issue #12)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings
from bot.utils.i18n import t

router = Router(name="rules")


@router.message(Command("setrules"), HasRole("admin"))
async def set_rules(message: Message, command: CommandObject, lang: str = "ru") -> None:
    if not command.args:
        await message.answer(t(lang, "rules_usage"))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "rules", {"text": command.args})
    await message.answer(t(lang, "rules_updated"))


@router.message(Command("rules"))
async def show_rules(message: Message, chat_settings: dict, lang: str = "ru") -> None:
    text = chat_settings.get("rules", {}).get("text")
    await message.answer(text if text else t(lang, "rules_empty"))
