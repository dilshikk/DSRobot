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

issue #7: цепочка подключена и к edited_message, иначе любой фильтр обходился правкой
сообщения. Для правок не считаются статистика и дубликаты (antispam).

issue #34: команды тоже проходят проверки. Раньше любой текст, начинающийся с "/",
сразу уходил в хендлеры, и "/ купить https://spam.ru" обходил все фильтры.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.enums import ContentType
from aiogram.types import Message, TelegramObject

from bot.handlers.chat.group_statistics import bump_stat
from bot.handlers.misc import alphabets
from bot.handlers.moderation import (
    anti_nsfw, antispam, approve_mode, banned_words, blocks, link_settings,
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

# Проверки, которые не имеют смысла для отредактированного сообщения.
SKIP_ON_EDIT: set[Check] = {antispam.check_duplicate_spam}

# Проверки, которые не применяются к командам: в чате с ограничением алфавита
# латинская команда (/price btc) удалялась бы всегда.
SKIP_ON_COMMAND: set[Check] = {alphabets.check_alphabet}


# Всё, что может прислать участник. Остальные типы — служебные (вход, смена названия, видеочат...):
# night/approve mode удаляют любое не служебное сообщение (issue #40), служебные не трогаем.
USER_CONTENT_TYPES = {
    ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO, ContentType.STICKER, ContentType.ANIMATION,
    ContentType.VOICE, ContentType.VIDEO_NOTE, ContentType.AUDIO, ContentType.DOCUMENT, ContentType.POLL,
    ContentType.CONTACT, ContentType.LOCATION, ContentType.VENUE, ContentType.DICE, ContentType.GAME,
    ContentType.STORY,
}


def _is_service(message: Message) -> bool:
    return message.content_type not in USER_CONTENT_TYPES


def _is_command(message: Message) -> bool:
    """Команда = entity bot_command в начале сообщения, а не просто текст с "/"."""
    return any(e.type == "bot_command" and e.offset == 0 for e in (message.entities or []))


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

        is_edit = event.edit_date is not None
        is_command = _is_command(event)

        role = data.get("chat_user_role", "member")
        for check in MESSAGE_CHECKS:
            if (is_edit and check in SKIP_ON_EDIT) or (is_command and check in SKIP_ON_COMMAND):
                continue
            try:
                if await check(event, settings, role):
                    return None  # сообщение удалено/наказано — дальше не передаём
            except Exception:
                # Ошибка одной проверки не должна ломать остальные.
                logger.exception("Moderation check %s failed", check.__name__)

        if is_command:
            if not is_edit:
                message_deletion.schedule_command_autodelete(event, settings)
            return await handler(event, data)

        if event.text and not is_edit:
            try:
                await bump_stat(event.chat.id, "messages_count")
            except Exception:
                logger.exception("Failed to bump message stats")

        return await handler(event, data)
