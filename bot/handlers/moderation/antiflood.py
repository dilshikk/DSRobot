"""
Настройки anti-flood (сама логика применения — в bot/middlewares/antiflood.py,
т.к. должна выполняться до диспетчеризации в конкретные хендлеры).
Ответы — на языке чата (issue #12).
"""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.middlewares.antiflood import DEFAULT_MUTE_MINUTES, FLOOD_ACTIONS
from bot.services.settings_service import update_settings
from bot.utils.i18n import t

router = Router(name="antiflood_settings")

MAX_PER_SECONDS = 3600
MAX_MUTE_MINUTES = 60 * 24 * 365


@router.message(Command("setflood"), HasRole("admin"))
async def set_flood(message: Message, command: CommandObject, lang: str = "ru") -> None:
    parts = (command.args or "").split()
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await message.answer(t(lang, "flood_usage"))
        return

    max_messages, per_seconds = int(parts[0]), int(parts[1])
    if max_messages < 1 or not 1 <= per_seconds <= MAX_PER_SECONDS:
        await message.answer(t(lang, "flood_invalid_limits", max_seconds=MAX_PER_SECONDS))
        return

    action = parts[2] if len(parts) > 2 else "mute"
    if action not in FLOOD_ACTIONS:
        await message.answer(t(lang, "flood_usage"))
        return

    mute_minutes = DEFAULT_MUTE_MINUTES
    if len(parts) > 3:
        if not parts[3].isdigit() or not 1 <= int(parts[3]) <= MAX_MUTE_MINUTES:
            await message.answer(t(lang, "flood_invalid_mute", max_minutes=MAX_MUTE_MINUTES))
            return
        mute_minutes = int(parts[3])

    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "antiflood", {
            "max_messages": max_messages, "per_seconds": per_seconds,
            "action": action, "mute_minutes": mute_minutes, "enabled": True,
        })
    suffix = t(lang, "flood_mute_suffix", minutes=mute_minutes) if action == "mute" else ""
    await message.answer(t(lang, "flood_set", messages=max_messages, seconds=per_seconds,
                           action=action, suffix=suffix))


@router.message(Command("floodoff"), HasRole("admin"))
async def flood_off(message: Message, lang: str = "ru") -> None:
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "antiflood", {"enabled": False})
    await message.answer(t(lang, "flood_disabled"))
