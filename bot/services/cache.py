"""Тонкая обёртка над redis.asyncio для кэша настроек, rate-limit счётчиков и state капчи."""
from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis, from_url

from bot.config import settings

redis: Redis = from_url(settings.redis_url, decode_responses=True)


async def get_json(key: str) -> Any | None:
    raw = await redis.get(key)
    return json.loads(raw) if raw else None


async def set_json(key: str, value: Any, ex: int | None = None) -> None:
    await redis.set(key, json.dumps(value), ex=ex)


async def incr_with_ttl(key: str, ttl_seconds: int) -> int:
    """Инкрементирует счётчик (antiflood/throttling) и выставляет TTL при первом инкременте."""
    val = await redis.incr(key)
    if val == 1:
        await redis.expire(key, ttl_seconds)
    return val
