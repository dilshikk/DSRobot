"""Log channel: канал, куда бот дублирует все санкции (см. services/moderation_actions.py)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import get_or_create_chat
from bot.utils.parsing import parse_chat_id

router = Router(name="log_channel")


@router.message(Command("setlogchannel"), HasRole("owner"))
async def set_log_channel(message, command: CommandObject) -> None:
    target_id = parse_chat_id(command.args)
    if target_id is None:
        await message.answer("Использование: /setlogchannel <id канала> (бот должен быть там админом)")
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        chat.log_channel_id = target_id
        await session.commit()
    await message.answer("\u2705 Лог-канал подключён.")
