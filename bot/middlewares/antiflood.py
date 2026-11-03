"""
Anti-flood middleware: считает сообщения пользователя в скользящем окне (Redis INCR+EXPIRE)
и применяет действие (mute/kick/ban) при превышении порога, заданного в chat_settings.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.services.cache import incr_with_ttl
from bot.services.moderation_actions import apply_sanction


class AntiFloodMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        settings = data.get("chat_settings", {}).get("antiflood", {})
        role = data.get("chat_user_role", "member")
        if not settings.get("enabled") or role in ("admin", "owner", "developer"):
            return await handler(event, data)

        key = f"antiflood:{event.chat.id}:{event.from_user.id}"
        count = await incr_with_ttl(key, settings.get("per_seconds", 8))

        if count > settings.get("max_messages", 7):
            await apply_sanction(
                bot=data["bot"], chat_id=event.chat.id, user_id=event.from_user.id,
                action=settings.get("action", "mute"), reason="Anti-flood: превышен лимит сообщений",
                actor_user_id=0,
            )
            return  # не пропускаем сообщение дальше в handler'ы

        return await handler(event, data)
