"""Max message length settings."""
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings

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


@router.message(F.text, ~F.text.startswith("/"))
async def enforce_max_length(message: Message, chat_settings: dict, chat_user_role: str = "member") -> None:
    cfg = chat_settings.get("max_message_length", {})
    if not cfg.get("enabled") or chat_user_role in ("admin", "owner", "developer"):
        return
    if len(message.text or "") > cfg.get("limit", 4000):
        try:
            await message.delete()
        except Exception:
            pass
