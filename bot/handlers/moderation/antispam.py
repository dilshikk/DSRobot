"""
Antispam: эвристики против дубликатов сообщений (одно и то же сообщение подряд N раз)
+ точка расширения под внешний CAS (Combot Anti-Spam) / собственную ML-модель.
Проверка вызывается из bot/middlewares/moderation_pipeline.py. Ответы — на языке чата (issue #12).
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.cache import redis
from bot.services.chat_lang import get_chat_lang
from bot.services.moderation_actions import apply_sanction
from bot.services.settings_service import update_settings
from bot.utils.i18n import t, toggle_text
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
        # Проверки из moderation_pipeline не получают handler data, язык берём из кэша.
        lang = await get_chat_lang(message.chat.id)
        await apply_sanction(message.bot, message.chat.id, message.from_user.id, "mute",
                              t(lang, "antispam_reason"), 0, duration_minutes=30)
        return True
    return False


@router.message(Command("antispam"), HasRole("admin"))
async def toggle_antispam(message: Message, chat_settings: dict, lang: str = "ru") -> None:
    new_state = not chat_settings.get("antispam", {}).get("enabled", True)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "antispam", {"enabled": new_state})
    await message.answer(toggle_text(lang, "feature_antispam", new_state))
