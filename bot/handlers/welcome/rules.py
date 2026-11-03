"""Rules."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings

router = Router(name="rules")


@router.message(Command("setrules"), HasRole("admin"))
async def set_rules(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Использование: /setrules <текст правил>")
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "rules", {"text": command.args})
    await message.answer("\u2705 Правила обновлены.")


@router.message(Command("rules"))
async def show_rules(message: Message, chat_settings: dict) -> None:
    text = chat_settings.get("rules", {}).get("text")
    await message.answer(text if text else "Правила для этого чата ещё не заданы.")
