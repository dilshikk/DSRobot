"""Topics settings: настройки форум-топиков супергруппы (создание/закрытие/ограничение фич по топику).

issue #43: TopicSettings.locked_features сохранялся, но нигде не читался. Теперь:
- /locktopic <тип> и /unlocktopic <тип> внутри топика запрещают/разрешают тип контента;
- /topiclocks показывает, что запрещено в текущем топике;
- check_topic_locks в moderation_pipeline удаляет запрещённые сообщения участников.
Блокировки кэшируются в Redis, чтобы не делать SELECT на каждое сообщение в топике.
"""
from __future__ import annotations

from typing import Callable

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import TopicSettings
from bot.filters.roles import HasRole
from bot.handlers.moderation.link_settings import extract_links
from bot.handlers.moderation.media_blocks import MEDIA_MAP
from bot.services.cache import get_json, redis, set_json
from bot.utils.permissions import is_privileged
from bot.utils.telegram import delete_message_safely

router = Router(name="topics_settings")

# Что можно запретить в топике: текст, ссылки и все типы медиа из /blockmedia.
LOCK_KINDS: dict[str, Callable[[Message], bool]] = {
    "text": lambda m: bool(m.text),
    "links": lambda m: bool(extract_links(m)),
    **MEDIA_MAP,
}
LOCKS_CACHE_TTL = 3600
NOT_IN_TOPIC = "Эта команда должна быть вызвана внутри топика."


def _locks_key(chat_id: int, topic_id: int) -> str:
    return f"topiclocks:{chat_id}:{topic_id}"


def enabled_locks(locked_features: dict | None) -> list[str]:
    """Только включённые и известные блокировки, в стабильном порядке."""
    features = locked_features or {}
    return [kind for kind in LOCK_KINDS if features.get(kind)]


async def get_topic_locks(chat_id: int, topic_id: int) -> list[str]:
    cached = await get_json(_locks_key(chat_id, topic_id))
    if cached is not None:
        return cached
    async with SessionFactory() as session:
        row = (await session.execute(select(TopicSettings).where(
            TopicSettings.chat_id == chat_id, TopicSettings.topic_id == topic_id
        ))).scalar_one_or_none()
    locks = enabled_locks(row.locked_features if row else None)
    # Пустой список тоже кэшируем: иначе каждое сообщение в топике без блокировок шло бы в БД.
    await set_json(_locks_key(chat_id, topic_id), locks, ex=LOCKS_CACHE_TTL)
    return locks


async def save_topic_lock(chat_id: int, topic_id: int, kind: str, locked: bool) -> list[str]:
    """Сохраняет блокировку. Топик мог быть создан не через бота — тогда запись создаётся."""
    async with SessionFactory() as session:
        row = (await session.execute(select(TopicSettings).where(
            TopicSettings.chat_id == chat_id, TopicSettings.topic_id == topic_id
        ))).scalar_one_or_none()
        if row is None:
            row = TopicSettings(chat_id=chat_id, topic_id=topic_id, name="", locked_features={})
            session.add(row)
        # Новый dict, а не правка на месте: JSON-колонка не отслеживает мутации.
        row.locked_features = {**(row.locked_features or {}), kind: locked}
        locks = enabled_locks(row.locked_features)
        await session.commit()
    await redis.delete(_locks_key(chat_id, topic_id))
    return locks


def _topic_id(message: Message) -> int | None:
    return message.message_thread_id if message.is_topic_message else None


@router.message(Command("newtopic"), HasRole("admin"))
async def create_topic(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Использование: /newtopic <название>")
        return
    topic = await message.bot.create_forum_topic(message.chat.id, name=command.args)
    async with SessionFactory() as session:
        session.add(TopicSettings(chat_id=message.chat.id, topic_id=topic.message_thread_id, name=command.args))
        await session.commit()
    await message.answer(f"\u2705 Топик «{command.args}» создан.")


@router.message(Command("closetopic"), HasRole("admin"))
async def close_topic(message: Message) -> None:
    if not message.message_thread_id:
        await message.answer(NOT_IN_TOPIC)
        return
    await message.bot.close_forum_topic(message.chat.id, message.message_thread_id)
    await message.answer("\U0001f512 Топик закрыт.")


async def _toggle_lock(message: Message, command: CommandObject, locked: bool) -> None:
    topic_id = _topic_id(message)
    if topic_id is None:
        await message.answer(NOT_IN_TOPIC)
        return
    kind = (command.args or "").strip().lower()
    if kind not in LOCK_KINDS:
        name = "locktopic" if locked else "unlocktopic"
        await message.answer(f"Использование: /{name} <{' | '.join(LOCK_KINDS)}>", parse_mode=None)
        return
    await save_topic_lock(message.chat.id, topic_id, kind, locked)
    text = f"\U0001f512 В этом топике запрещено: {kind}." if locked else f"\U0001f513 В этом топике снова разрешено: {kind}."
    await message.answer(text, parse_mode=None)


@router.message(Command("locktopic"), HasRole("admin"))
async def lock_topic_feature(message: Message, command: CommandObject) -> None:
    await _toggle_lock(message, command, locked=True)


@router.message(Command("unlocktopic"), HasRole("admin"))
async def unlock_topic_feature(message: Message, command: CommandObject) -> None:
    await _toggle_lock(message, command, locked=False)


@router.message(Command("topiclocks"), HasRole("admin"))
async def show_topic_locks(message: Message) -> None:
    topic_id = _topic_id(message)
    if topic_id is None:
        await message.answer(NOT_IN_TOPIC)
        return
    locks = await get_topic_locks(message.chat.id, topic_id)
    text = ("\U0001f512 Запрещено в топике: " + ", ".join(locks)) if locks else "В этом топике ничего не запрещено."
    await message.answer(text, parse_mode=None)


async def check_topic_locks(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    """Вызывается из moderation_pipeline: удаляет контент, запрещённый в топике."""
    topic_id = _topic_id(message)
    if topic_id is None or is_privileged(chat_user_role):
        return False
    locks = await get_topic_locks(message.chat.id, topic_id)
    if not any(LOCK_KINDS[kind](message) for kind in locks if kind in LOCK_KINDS):
        return False
    await delete_message_safely(message)
    return True
