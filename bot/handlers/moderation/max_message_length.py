"""Max message length settings. Проверка вызывается из moderation_pipeline.
Ответы — на языке чата (issue #12)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings
from bot.utils.i18n import t
from bot.utils.permissions import is_privileged
from bot.utils.telegram import delete_message_safely

router = Router(name="max_message_length")


def max_len_text(lang: str, limit: int) -> str:
    # Раньше здесь был \u2014 внутри выражения f-строки — SyntaxError на Python < 3.12.
    return t(lang, "maxlen_set", limit=limit if limit > 0 else t(lang, "maxlen_off"))


@router.message(Command("setmaxlen"), HasRole("admin"))
async def set_max_len(message: Message, command: CommandObject, lang: str = "ru") -> None:
    if not command.args or not command.args.isdigit():
        await message.answer(t(lang, "maxlen_usage"))
        return
    limit = int(command.args)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "max_message_length", {
            "enabled": limit > 0, "limit": limit,
        })
    await message.answer(max_len_text(lang, limit))


async def check_max_length(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    cfg = chat_settings.get("max_message_length", {})
    if not message.text or not cfg.get("enabled") or is_privileged(chat_user_role):
        return False
    if len(message.text) <= cfg.get("limit", 4000):
        return False
    await delete_message_safely(message)
    return True
