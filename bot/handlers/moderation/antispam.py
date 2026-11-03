"""
Antispam: эвристики против дубликатов сообщений (одно и то же сообщение подряд N раз)
+ точка расширения под внешний CAS (Combot Anti-Spam) / собственную ML-модель.
Проверка вызывается из bot/middlewares/moderation_pipeline.py.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.filters.roles import HasRole
from bot.services.cache import redis
from bot.services.moderation_actions import apply_sanction
from bot.services.settings_service import update_settings
from bot.database import SessionFactory
from bot.utils.permissions import is_privileged

router = Router(name="antispam")

DUPLICATE_THRESHOLD = 3


async def check_duplicate_spam(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    if not message.text or not chat_settings.get("antispam", {}).get("enabled") or is_privileged(chat_user_role):
        return False
    key = f"lastmsg:{message.chat.id}:{message.from_user.id}"
    count_key = f"dupcount:{message.chat.id}:{message.from_user.id}"
    prev = await redis.get(key)
    await redis.set(key, message.text, ex=30)
    if prev != message.text:
        await redis.delete(count_key)
        return False

    count = await redis.incr(count_key)
    await redis.expire(count_key, 30)
    if count >= DUPLICATE_THRESHOLD:
        await redis.delete(count_key)
        await apply_sanction(message.bot, message.chat.id, message.from_user.id, "mute",
                              "Antispam: повторяющиеся сообщения", 0, duration_minutes=30)
        return True
    return False


@router.message(Command("antispam"), HasRole("admin"))
async def toggle_antispam(message, chat_settings: dict) -> None:
    new_state = not chat_settings.get("antispam", {}).get("enabled", True)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "antispam", {"enabled": new_state})
    await message.answer(f"Antispam: {'включён' if new_state else 'выключен'}")
