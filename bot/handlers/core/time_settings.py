"""UTC Time settings — сдвиг часового пояса чата для night_mode/статистики/рассылок."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.recurring import reschedule_chat
from bot.services.settings_service import get_or_create_chat

router = Router(name="time_settings")

MIN_OFFSET, MAX_OFFSET = -12, 14


@router.message(Command("setutc"), HasRole("admin"))
async def set_utc(message: Message, command: CommandObject) -> None:
    raw = (command.args or "").strip()
    if not raw.lstrip("+-").isdigit() or not MIN_OFFSET <= int(raw) <= MAX_OFFSET:
        await message.answer("Использование: /setutc <-12..+14>")
        return
    offset = int(raw)
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        chat.utc_offset = offset
        await session.commit()
    # Рассылки чата сразу переходят на новый часовой пояс (issue #10).
    await reschedule_chat(message.chat.id)
    await message.answer(f"\U0001f550 Часовой пояс чата установлен: UTC{offset:+d}")
