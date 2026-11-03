"""Max message length settings. Проверка вызывается из moderation_pipeline."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings
from bot.utils.permissions import is_privileged
from bot.utils.telegram import delete_message_safely

router = Router(name="max_message_length")


@router.message(Command("setmaxlen"), HasRole("admin"))
async def set_max_len(message: Message, command: CommandObject) -> None:
    if not command.args or not command.args.isdigit():
        await message.answer("Использование: /setmaxlen <символов> (0 = выключить)")
        return
    limit = int(command.args)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "max_message_length", {
            "enabled": limit > 0, "limit": limit,
        })
    await message.answer(f"\u2705 Максимальная длина сообщения: {limit or '\u2014 (выкл.)'}")


async def check_max_length(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    cfg = chat_settings.get("max_message_length", {})
    if not message.text or not cfg.get("enabled") or is_privileged(chat_user_role):
        return False
    if len(message.text) <= cfg.get("limit", 4000):
        return False
    await delete_message_safely(message)
    return True
