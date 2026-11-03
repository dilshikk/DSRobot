"""
Триггеры чата: заметки (#заметка) и magic-ответы стикером/GIF (issue #51).

Обе функции используют таблицу personal_commands. Раньше на каждое текстовое сообщение
шёл SELECT всех триггеров чата. Теперь список кэшируется в Redis (как banned words) и
сбрасывается при /addnote, /delnote, /addmagic, /delmagic.

Разделение по самому триггеру: заметка начинается с «#», magic-триггер — ключевое слово без «#».
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import PersonalCommand
from bot.services.cache import get_json, redis, set_json
from bot.utils.text_match import find_word

logger = logging.getLogger(__name__)

TRIGGERS_CACHE_TTL = 600
NOTE_PREFIX = "#"
MAX_TRIGGER_LENGTH = 128  # PersonalCommand.trigger — String(128)
MAGIC_TYPES = ("sticker", "gif")

# Тип ответа -> метод Message, которым он отправляется.
_SENDERS = {
    "text": "answer",
    "photo": "answer_photo",
    "sticker": "answer_sticker",
    "gif": "answer_animation",
    "video": "answer_video",
    "document": "answer_document",
}


@dataclass(frozen=True)
class Trigger:
    trigger: str
    response_type: str
    content: str

    @property
    def is_note(self) -> bool:
        return self.trigger.startswith(NOTE_PREFIX)

    @property
    def is_magic(self) -> bool:
        return not self.is_note and self.response_type in MAGIC_TYPES


def _cache_key(chat_id: int) -> str:
    return f"triggers:{chat_id}"


async def get_triggers(chat_id: int) -> list[Trigger]:
    """Все триггеры чата. Пустой список тоже кэшируется: чаты без заметок не ходят в БД."""
    cached = await get_json(_cache_key(chat_id))
    if cached is None:
        async with SessionFactory() as session:
            rows = (await session.execute(
                select(PersonalCommand.trigger, PersonalCommand.response_type, PersonalCommand.response_content)
                .where(PersonalCommand.chat_id == chat_id)
            )).all()
        cached = [[row.trigger, row.response_type, row.response_content] for row in rows]
        await set_json(_cache_key(chat_id), cached, ex=TRIGGERS_CACHE_TTL)
    return [Trigger(*item) for item in cached]


async def invalidate_triggers(chat_id: int) -> None:
    await redis.delete(_cache_key(chat_id))


def find_note(text: str, triggers: list[Trigger]) -> Trigger | None:
    """Заметка по первому слову сообщения: «#rules пожалуйста» -> #rules."""
    if not text.startswith(NOTE_PREFIX):
        return None
    key = text.split(maxsplit=1)[0].lower()
    return next((t for t in triggers if t.is_note and t.trigger == key), None)


def find_magic(text: str, triggers: list[Trigger]) -> Trigger | None:
    """Magic-ответ на ключевое слово, встреченное в тексте целым словом."""
    magic = {t.trigger: t for t in triggers if t.is_magic}
    word = find_word(text, list(magic))
    return magic.get(word) if word else None


def extract_response(message: Message) -> tuple[str, str] | None:
    """(тип, содержимое) из сообщения, на которое ответил админ. GIF проверяется раньше
    документа: у анимации Telegram заполняет оба поля."""
    if message.sticker:
        return "sticker", message.sticker.file_id
    if message.animation:
        return "gif", message.animation.file_id
    if message.photo:
        return "photo", message.photo[-1].file_id
    if message.video:
        return "video", message.video.file_id
    if message.document:
        return "document", message.document.file_id
    if message.text:
        # html_text сохраняет форматирование и экранирует «<», ответ уходит с HTML по умолчанию.
        return "text", message.html_text
    return None


async def send_response(message: Message, trigger: Trigger) -> None:
    method_name = _SENDERS.get(trigger.response_type)
    if method_name is None:
        logger.warning("Unknown trigger response type %r in chat %s", trigger.response_type, message.chat.id)
        return
    try:
        await getattr(message, method_name)(trigger.content)
    except TelegramAPIError as exc:
        # Например, file_id от другого бота (клона) или удалённый файл.
        logger.warning("Cannot send trigger %r in chat %s: %s", trigger.trigger, message.chat.id, exc)
