"""
Язык чата для кода, который работает вне обычного сообщения (issue #12):
нажатия кнопок капчи, таймауты из планировщика, уведомления о правах.

ChatContextMiddleware и так читает Chat.lang для каждого сообщения, а здесь язык
кэшируется в Redis, чтобы фоновые задачи не ходили в PostgreSQL. /setlang
обновляет кэш через remember_chat_lang().
"""
from __future__ import annotations

from bot.config import settings
from bot.database import SessionFactory
from bot.database.models import Chat
from bot.services.cache import redis
from bot.utils.i18n import normalize_lang

LANG_CACHE_TTL = 3600


def _key(chat_id: int) -> str:
    return f"chat_lang:{chat_id}"


def default_lang() -> str:
    return normalize_lang(settings.default_lang)


async def get_chat_lang(chat_id: int) -> str:
    cached = await redis.get(_key(chat_id))
    if cached:
        return normalize_lang(cached, default_lang())
    async with SessionFactory() as session:
        chat = await session.get(Chat, chat_id)
    lang = normalize_lang(chat.lang if chat else None, default_lang())
    await redis.set(_key(chat_id), lang, ex=LANG_CACHE_TTL)
    return lang


async def remember_chat_lang(chat_id: int, lang: str) -> None:
    await redis.set(_key(chat_id), normalize_lang(lang, default_lang()), ex=LANG_CACHE_TTL)
