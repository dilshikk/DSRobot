"""Log channel: канал, куда бот дублирует все санкции (см. services/moderation_actions.py).
Ответы — на языке чата (issue #12)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import get_or_create_chat
from bot.utils.i18n import t

router = Router(name="log_channel")


@router.message(Command("setlogchannel"), HasRole("owner"))
async def set_log_channel(message, command: CommandObject, lang: str = "ru") -> None:
    if not command.args or not command.args.lstrip("-").isdigit():
        await message.answer(t(lang, "setlogchannel_usage"))
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        chat.log_channel_id = int(command.args)
        await session.commit()
    await message.answer(t(lang, "setlogchannel_done"))
