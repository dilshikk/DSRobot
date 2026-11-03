"""UTC Time settings — сдвиг часового пояса чата для night_mode/статистики/рассылок."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import get_or_create_chat

router = Router(name="time_settings")


@router.message(Command("setutc"), HasRole("admin"))
async def set_utc(message: Message, command: CommandObject) -> None:
    if not command.args or not command.args.lstrip("+-").isdigit():
        await message.answer("Использование: /setutc <-12..+14>")
        return
    offset = int(command.args)
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        chat.utc_offset = offset
        await session.commit()
    await message.answer(f"\U0001f550 Часовой пояс чата установлен: UTC{offset:+d}")
