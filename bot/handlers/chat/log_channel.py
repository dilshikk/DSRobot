"""Log channel: канал, куда бот дублирует все санкции (см. services/moderation_actions.py)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import get_or_create_chat

router = Router(name="log_channel")


@router.message(Command("setlogchannel"), HasRole("owner"))
async def set_log_channel(message, command: CommandObject) -> None:
    if not command.args or not command.args.lstrip("-").isdigit():
        await message.answer("Использование: /setlogchannel <id канала> (бот должен быть там админом)")
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        chat.log_channel_id = int(command.args)
        await session.commit()
    await message.answer("\u2705 Лог-канал подключён.")
