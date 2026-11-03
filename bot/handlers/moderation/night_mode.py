"""Night mode: в заданный диапазон часов (UTC + chat.utc_offset) чат уходит в read-only для обычных участников."""
from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import get_or_create_chat, update_settings

router = Router(name="night_mode")


@router.message(Command("nightmode"), HasRole("admin"))
async def set_night_mode(message: Message, command: CommandObject) -> None:
    """Использование: /nightmode <start_hour> <end_hour> | off"""
    args = (command.args or "").split()
    if args and args[0] == "off":
        async with SessionFactory() as session:
            await update_settings(session, message.chat.id, "night_mode", {"enabled": False})
        await message.answer("Night mode выключен.")
        return
    if len(args) != 2 or not all(a.isdigit() for a in args):
        await message.answer("Использование: /nightmode <час_начала 0-23> <час_конца 0-23> | off")
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "night_mode", {
            "enabled": True, "start_hour": int(args[0]), "end_hour": int(args[1]),
        })
    await message.answer(f"\U0001f319 Night mode: {args[0]}:00–{args[1]}:00")


@router.message(F.text, ~F.text.startswith("/"))
async def enforce_night_mode(message: Message, chat_settings: dict, chat_user_role: str = "member") -> None:
    cfg = chat_settings.get("night_mode", {})
    if not cfg.get("enabled") or chat_user_role in ("admin", "owner", "developer"):
        return

    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        offset = chat.utc_offset

    hour = (datetime.now(timezone.utc).hour + offset) % 24
    start, end = cfg["start_hour"], cfg["end_hour"]
    in_night = (start <= hour < end) if start < end else (hour >= start or hour < end)

    if in_night:
        try:
            await message.delete()
        except Exception:
            pass
