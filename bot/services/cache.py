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
    """
    Инкрементирует счётчик (antiflood/antispam) с TTL от первого инкремента.

    issue #49: раньше INCR и EXPIRE были отдельными командами: если процесс падал
между ними, ключ оставался без TTL и счётчик рос вечно. Теперь SET NX EX создаёт
ключ сразу с TTL, а INCR идёт в той же транзакции MULTI/EXEC.
    """
    async with redis.pipeline(transaction=True) as pipe:
        pipe.set(key, 0, ex=ttl_seconds, nx=True)
        pipe.incr(key)
        _, value = await pipe.execute()
    return int(value)


async def close_redis() -> None:
    """Закрывает пул соединений Redis при остановке бота (issue #13)."""
    await redis.aclose()
