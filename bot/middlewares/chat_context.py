"""
Chat Context Middleware.
Загружает/создаёт Chat + ChatSettings, сохраняет отправителя в users/chat_users,
определяет роль отправителя в чате (Telegram + custom-роли бота, с кэшем в Redis,
см. services/roles.py) и прокидывает всё в handler data.
Поддерживает анонимных админов (sender_chat) — Support for anonymous admins.

issue #11: в data кладутся chat_user_role и chat_user_permissions (права custom-роли).
issue #12: в data["lang"] кладётся язык ответов — Chat.lang в группах (/setlang),
язык Telegram-клиента пользователя в личке.
issue #47: активность отмечается в ChatUser.last_seen_at (по чату), а не только в глобальном
User.last_seen; написавший участник считается снова состоящим в чате (left_at = NULL).
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, TelegramObject, User as TgUser

from bot.config import settings
from bot.database import SessionFactory
from bot.services.cache import get_json, set_json
from bot.services.roles import resolve_access
from bot.services.settings_service import get_or_create_chat, get_settings
from bot.services.user_service import seen_cache_key, touch_chat_user, upsert_tg_user
from bot.utils.i18n import normalize_lang

# Как часто (сек) обновлять users/chat_users для одного и того же человека в чате.
# Без этого каждое сообщение давало бы лишнюю запись в PostgreSQL.
SEEN_CACHE_TTL = 600
LINKED_CHAT_CACHE_TTL = 3600

logger = logging.getLogger(__name__)


async def linked_chat_id(bot: Bot, chat_id: int) -> int | None:
    """id канала, к которому группа привязана как обсуждение (кэш в Redis, 0 = не привязана)."""
    key = f"linked_chat:{chat_id}"
    cached = await get_json(key)
    if cached is None:
        try:
            cached = (await bot.get_chat(chat_id)).linked_chat_id or 0
        except TelegramAPIError as exc:
            logger.warning("Cannot get linked chat for %s: %s", chat_id, exc)
            return None
        await set_json(key, cached, ex=LINKED_CHAT_CACHE_TTL)
    return cached or None


async def is_linked_channel_post(bot: Bot, message: Message) -> bool:
    """Автопересылка поста канала или сообщение от имени привязанного канала (issue #44)."""
    if message.is_automatic_forward:
        return True
    sender = message.sender_chat
    if sender is None or sender.type != "channel" or sender.id == message.chat.id:
        return False
    return await linked_chat_id(bot, message.chat.id) == sender.id


def _extract_message(event: TelegramObject) -> Message | None:
    # Middleware висит на dp.message, поэтому event — это сам Message.
    # Раньше код искал event.message / data["event_message"], которых у Message нет,
    # и middleware молча пропускал все сообщения без контекста.
    if isinstance(event, Message):
        return event
    return getattr(event, "message", None)


class ChatContextMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        message = _extract_message(event)
        chat = message.chat if message else None
        default_lang = normalize_lang(settings.default_lang)

        if chat is None or chat.type == "private":
            user = message.from_user if message else None
            data["lang"] = normalize_lang(user.language_code if user else None, default_lang)
            return await handler(event, data)

        user = message.from_user
        is_anonymous_admin = bool(message.sender_chat and message.sender_chat.id == chat.id)
        # Посты привязанного канала не модерируются, но и прав админа в группе не дают.
        data["is_linked_channel"] = await is_linked_channel_post(data["bot"], message)

        async with SessionFactory() as session:
            db_chat = await get_or_create_chat(session, chat.id, chat.title or "", chat.type)
            data["lang"] = normalize_lang(db_chat.lang, default_lang)
            # utc_offset — для проверок пайплайна (night mode), чтобы не ходить в БД на каждое сообщение.
            data["chat_settings"] = {**await get_settings(session, chat.id), "utc_offset": db_chat.utc_offset or 0}

            # Анонимный админ приходит от служебного аккаунта GroupAnonymousBot — его не сохраняем.
            if user and not is_anonymous_admin and not data["is_linked_channel"]:
                await self._remember_users(session, chat.id, [user, *(message.new_chat_members or [])])

        if is_anonymous_admin:
            data["chat_user_role"] = "admin"
            data["chat_user_permissions"] = frozenset()
            data["is_anonymous_admin"] = True
            return await handler(event, data)

        if user:
            access = await resolve_access(data["bot"], chat.id, user.id)
            data["chat_user_role"] = access.role
            data["chat_user_permissions"] = access.permissions

        return await handler(event, data)

    @staticmethod
    async def _remember_users(session, chat_id: int, users: list[TgUser]) -> None:
        fresh: list[TgUser] = []
        for tg_user in {u.id: u for u in users}.values():
            if await get_json(seen_cache_key(chat_id, tg_user.id)) is not None:
                continue
            await upsert_tg_user(session, tg_user)
            await touch_chat_user(session, chat_id, tg_user.id)
            fresh.append(tg_user)
        if fresh:
            await session.commit()
            for tg_user in fresh:
                await set_json(seen_cache_key(chat_id, tg_user.id), 1, ex=SEEN_CACHE_TTL)
