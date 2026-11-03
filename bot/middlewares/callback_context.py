"""
Контекст чата для нажатий inline-кнопок (issue #11).

ChatContextMiddleware рассчитан на Message: у callback_query.message автор — сам бот,
поэтому роль нужно определять по callback.from_user. Здесь в handler data кладутся
chat_settings, chat_user_role и chat_user_permissions, как и для сообщений.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from bot.database import SessionFactory
from bot.services.roles import resolve_access
from bot.services.settings_service import get_settings


class CallbackContextMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery) or event.message is None:
            return await handler(event, data)
        chat = event.message.chat
        if chat.type == "private":
            return await handler(event, data)

        async with SessionFactory() as session:
            data["chat_settings"] = await get_settings(session, chat.id)
        access = await resolve_access(data["bot"], chat.id, event.from_user.id)
        data["chat_user_role"] = access.role
        data["chat_user_permissions"] = access.permissions
        return await handler(event, data)
