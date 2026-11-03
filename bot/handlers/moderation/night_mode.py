"""Night mode: в заданный диапазон часов (UTC + chat.utc_offset) чат уходит в read-only для обычных участников.
Проверка вызывается из moderation_pipeline. Ответы — на языке чата (issue #12)."""
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import get_or_create_chat, update_settings
from bot.utils.i18n import t
from bot.utils.permissions import is_privileged
from bot.utils.telegram import delete_message_safely

router = Router(name="night_mode")


def _parse_hours(args: list[str]) -> tuple[int, int] | None:
    if len(args) != 2 or not all(a.isdigit() for a in args):
        return None
    start, end = int(args[0]), int(args[1])
    if not (0 <= start <= 23 and 0 <= end <= 23):
        return None
    return start, end


@router.message(Command("nightmode"), HasRole("admin"))
async def set_night_mode(message: Message, command: CommandObject, lang: str = "ru") -> None:
    """Использование: /nightmode <start_hour> <end_hour> | off"""
    args = (command.args or "").split()
    if args and args[0] == "off":
        async with SessionFactory() as session:
            await update_settings(session, message.chat.id, "night_mode", {"enabled": False})
        await message.answer(t(lang, "night_disabled"))
        return
    hours = _parse_hours(args)
    if hours is None:
        await message.answer(t(lang, "night_usage"))
        return
    start, end = hours
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "night_mode", {
            "enabled": True, "start_hour": start, "end_hour": end,
        })
    await message.answer(t(lang, "night_set", start=start, end=end))


async def check_night_mode(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    cfg = chat_settings.get("night_mode", {})
    if not message.text or not cfg.get("enabled") or is_privileged(chat_user_role):
        return False

    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        offset = chat.utc_offset

    hour = (datetime.now(timezone.utc).hour + offset) % 24
    start, end = cfg["start_hour"], cfg["end_hour"]
    in_night = (start <= hour < end) if start < end else (hour >= start or hour < end)
    if not in_night:
        return False

    await delete_message_safely(message)
    return True
