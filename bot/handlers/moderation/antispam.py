"""
Antispam: эвристики против дубликатов сообщений (одно и то же сообщение подряд N раз)
+ точка расширения под внешний CAS (Combot Anti-Spam) / собственную ML-модель.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.filters.roles import HasRole
from bot.services.cache import redis
from bot.services.moderation_actions import apply_sanction
from bot.services.settings_service import update_settings
from bot.database import SessionFactory

router = Router(name="antispam")

DUPLICATE_THRESHOLD = 3


@router.message(F.text, ~F.text.startswith("/"))
async def check_duplicate_spam(message: Message, chat_settings: dict, chat_user_role: str = "member") -> None:
    if not chat_settings.get("antispam", {}).get("enabled") or chat_user_role in ("admin", "owner", "developer"):
        return
    key = f"lastmsg:{message.chat.id}:{message.from_user.id}"
    prev = await redis.get(key)
    if prev == message.text:
        count_key = f"dupcount:{message.chat.id}:{message.from_user.id}"
        count = await redis.incr(count_key)
        await redis.expire(count_key, 30)
        if count >= DUPLICATE_THRESHOLD:
            await apply_sanction(message.bot, message.chat.id, message.from_user.id, "mute",
                                  "Antispam: повторяющиеся сообщения", 0, duration_minutes=30)
    else:
        await redis.delete(f"dupcount:{message.chat.id}:{message.from_user.id}")
    await redis.set(key, message.text or "", ex=30)


@router.message(Command("antispam"), HasRole("admin"))
async def toggle_antispam(message, chat_settings: dict) -> None:
    new_state = not chat_settings.get("antispam", {}).get("enabled", True)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "antispam", {"enabled": new_state})
    await message.answer(f"Antispam: {'включён' if new_state else 'выключен'}")
