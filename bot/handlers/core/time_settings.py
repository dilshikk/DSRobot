"""UTC Time settings — сдвиг часового пояса чата для night_mode/статистики/рассылок.
Ответы — на языке чата (issue #12)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.recurring import reschedule_chat
from bot.services.settings_service import get_or_create_chat
from bot.utils.i18n import t

router = Router(name="time_settings")

MIN_OFFSET, MAX_OFFSET = -12, 14


def parse_offset(raw: str | None) -> int | None:
    """'+3' -> 3, '-12' -> -12. Вне диапазона или не число -> None."""
    value = (raw or "").strip()
    try:
        offset = int(value)
    except ValueError:
        return None
    return offset if MIN_OFFSET <= offset <= MAX_OFFSET else None


@router.message(Command("setutc"), HasRole("admin"))
async def set_utc(message: Message, command: CommandObject, lang: str = "ru") -> None:
    offset = parse_offset(command.args)
    if offset is None:
        # Раньше подсказка была «/setutc <-12..+14>» и ломала HTML-разметку — админ ничего не получал.
        await message.answer(t(lang, "setutc_usage", min=MIN_OFFSET, max=f"{MAX_OFFSET:+d}"))
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        chat.utc_offset = offset
        await session.commit()
    # Рассылки чата сразу переходят на новый часовой пояс (issue #10).
    await reschedule_chat(message.chat.id)
    await message.answer(t(lang, "setutc_done", offset=f"{offset:+d}"))
