"""
Настройки anti-flood (сама логика применения — в bot/middlewares/antiflood.py,
т.к. должна выполняться до диспетчеризации в конкретные хендлеры).
"""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.middlewares.antiflood import DEFAULT_MUTE_MINUTES, FLOOD_ACTIONS
from bot.services.settings_service import update_settings

router = Router(name="antiflood_settings")

USAGE = (
    "Использование: /setflood СООБЩЕНИЙ СЕКУНД [mute|kick|ban] [МИНУТ_МУТА]\n"
    "Например: /setflood 7 8 mute 30"
)
MAX_PER_SECONDS = 3600
MAX_MUTE_MINUTES = 60 * 24 * 365


@router.message(Command("setflood"), HasRole("admin"))
async def set_flood(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await message.answer(USAGE)
        return

    max_messages, per_seconds = int(parts[0]), int(parts[1])
    if max_messages < 1 or not 1 <= per_seconds <= MAX_PER_SECONDS:
        await message.answer(f"Сообщений должно быть не меньше 1, секунд — от 1 до {MAX_PER_SECONDS}.")
        return

    action = parts[2] if len(parts) > 2 else "mute"
    if action not in FLOOD_ACTIONS:
        await message.answer(USAGE)
        return

    mute_minutes = DEFAULT_MUTE_MINUTES
    if len(parts) > 3:
        if not parts[3].isdigit() or not 1 <= int(parts[3]) <= MAX_MUTE_MINUTES:
            await message.answer(f"Длительность мута — целое число минут от 1 до {MAX_MUTE_MINUTES}.")
            return
        mute_minutes = int(parts[3])

    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "antiflood", {
            "max_messages": max_messages, "per_seconds": per_seconds,
            "action": action, "mute_minutes": mute_minutes, "enabled": True,
        })
    suffix = f" на {mute_minutes} мин." if action == "mute" else ""
    await message.answer(f"\u2705 Anti-flood: {max_messages} сообщений / {per_seconds}с \u2192 {action}{suffix}")


@router.message(Command("floodoff"), HasRole("admin"))
async def flood_off(message: Message) -> None:
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "antiflood", {"enabled": False})
    await message.answer("Anti-flood выключен.")
