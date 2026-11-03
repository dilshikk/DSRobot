"""
Throttling / Rate Limiter middleware — защита от спама командами (не путать с anti-flood
фичей для обычных сообщений, см. handlers/moderation/antiflood.py).
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.services.cache import redis

DEFAULT_RATE_LIMIT_SEC = 1.0


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = DEFAULT_RATE_LIMIT_SEC) -> None:
        self.rate_limit = rate_limit

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        key = f"throttle:{event.chat.id}:{event.from_user.id}"
        if await redis.exists(key):
            return  # молча игнорируем — сообщение прилетело слишком быстро
        await redis.set(key, 1, px=int(self.rate_limit * 1000))

        return await handler(event, data)
