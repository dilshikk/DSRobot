"""
Moderation pipeline middleware (issue #1).

Раньше каждая авто-проверка (antispam, banned words, ссылки, медиа-блоки и т.д.) была
отдельным message-хендлером с фильтром вроде `F.text`. В aiogram 3 событие обрабатывает
только ПЕРВЫЙ подходящий хендлер, поэтому antispam перехватывал весь текст и до остальных
проверок очередь не доходила, а `maybe_autodelete_command` перехватывал команды из
роутеров, зарегистрированных после него.

Теперь все фоновые проверки выполняются здесь по очереди для каждого сообщения.
Если проверка удалила сообщение или применила санкцию (вернула True), цепочка
прерывается и хендлеры не вызываются. Иначе сообщение идёт дальше в роутеры
(команды, заметки #триггер, magic-стикеры).
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.handlers.chat.group_statistics import bump_stat
from bot.handlers.moderation import (
    alphabets, anti_nsfw, antispam, approve_mode, banned_words, blocks, link_settings,
    masked_users, max_message_length, media_blocks, message_deletion, night_mode,
)

logger = logging.getLogger(__name__)

Check = Callable[[Message, dict, str], Awaitable[bool]]

# Порядок важен: сначала самые "дешёвые" и строгие проверки.
MESSAGE_CHECKS: list[Check] = [
    approve_mode.check_unapproved,
    night_mode.check_night_mode,
    blocks.check_forward_block,
    media_blocks.check_media_block,
    anti_nsfw.check_nsfw,
    masked_users.check_masked_links,
    link_settings.check_links,
    banned_words.check_banned_words,
    alphabets.check_alphabet,
    max_message_length.check_max_length,
    antispam.check_duplicate_spam,
]


def _is_service(message: Message) -> bool:
    return bool(message.new_chat_members or message.left_chat_member or message.pinned_message)


class ModerationPipelineMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.chat.type == "private" or event.from_user is None:
            return await handler(event, data)

        settings = data.get("chat_settings")
        # Служебные события (вступление/выход/закреп) обрабатываются в welcome/service_events.py
        if settings is None or _is_service(event):
            return await handler(event, data)

        if (event.text or "").startswith("/"):
            message_deletion.schedule_command_autodelete(event, settings)
            return await handler(event, data)

        role = data.get("chat_user_role", "member")
        for check in MESSAGE_CHECKS:
            try:
                if await check(event, settings, role):
                    return None  # сообщение удалено/наказано — дальше не передаём
            except Exception:
                # Ошибка одной проверки не должна ломать остальные.
                logger.exception("Moderation check %s failed", check.__name__)

        if event.text:
            try:
                await bump_stat(event.chat.id, "messages_count")
            except Exception:
                logger.exception("Failed to bump message stats")

        return await handler(event, data)
