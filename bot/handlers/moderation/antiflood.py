"""
Настройки anti-flood (сама логика применения — в bot/middlewares/antiflood.py,
т.к. должна выполняться до диспетчеризации в конкретные хендлеры).
"""
from aiogram import Router
from aiogram.filters import Command, CommandObject

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings

router = Router(name="antiflood_settings")


@router.message(Command("setflood"), HasRole("admin"))
async def set_flood(message, command: CommandObject) -> None:
    """Использование: /setflood <max_messages> <per_seconds> [mute|kick|ban]"""
    parts = (command.args or "").split()
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await message.answer("Использование: /setflood <макс_сообщений> <за_секунд> [mute|kick|ban]")
        return
    action = parts[2] if len(parts) > 2 and parts[2] in ("mute", "kick", "ban") else "mute"
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "antiflood", {
            "max_messages": int(parts[0]), "per_seconds": int(parts[1]), "action": action, "enabled": True,
        })
    await message.answer(f"\u2705 Anti-flood: {parts[0]} сообщений / {parts[1]}с \u2192 {action}")


@router.message(Command("floodoff"), HasRole("admin"))
async def flood_off(message) -> None:
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "antiflood", {"enabled": False})
    await message.answer("Anti-flood выключен.")
