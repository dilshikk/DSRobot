"""
Combot Anti-Spam (CAS, https://cas.chat) — общая база известных спамеров Telegram (issue #14).

GET {CAS_API_URL}?user_id=ID отвечает {"ok": true, ...}, если аккаунт в базе,
и {"ok": false, "description": "Record not found."}, если нет.

Результат кэшируется в Redis на CAS_CACHE_TTL, чтобы не ходить в CAS на каждое сообщение.
Если сервис недоступен, пользователь считается чистым (fail-open): сбой внешнего API
не должен блокировать чат. Повторная попытка — не раньше чем через CAS_ERROR_TTL.
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp

from bot.config import settings
from bot.services.cache import redis

logger = logging.getLogger(__name__)

CAS_TIMEOUT_SEC = 3
CAS_CACHE_TTL = 6 * 3600
CAS_ERROR_TTL = 300

_BANNED, _CLEAN, _UNKNOWN = "1", "0", "?"


def cas_cache_key(user_id: int) -> str:
    return f"cas:{user_id}"


async def fetch_cas_status(user_id: int) -> bool | None:
    """True — в базе CAS, False — нет, None — сервис не ответил."""
    try:
        timeout = aiohttp.ClientTimeout(total=CAS_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.get(settings.cas_api_url, params={"user_id": str(user_id)}) as resp:
                if resp.status != 200:
                    logger.warning("CAS check for %s: HTTP %s", user_id, resp.status)
                    return None
                data = await resp.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.warning("CAS check for %s failed: %s", user_id, exc)
        return None
    if not isinstance(data, dict):
        return None
    return data.get("ok") is True


async def is_cas_banned(user_id: int) -> bool:
    key = cas_cache_key(user_id)
    cached = await redis.get(key)
    if cached is not None:
        return cached == _BANNED

    status = await fetch_cas_status(user_id)
    if status is None:
        await redis.set(key, _UNKNOWN, ex=CAS_ERROR_TTL)
        return False
    await redis.set(key, _BANNED if status else _CLEAN, ex=CAS_CACHE_TTL)
    return status
