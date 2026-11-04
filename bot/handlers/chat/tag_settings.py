"""
/tagall — упоминание участников чата (с батчингом, чтобы не упереться в rate-limit).

issue #97:
- текст после команды экранируется (parse_mode=HTML): `/tagall a < b & c` больше не падает,
  а `<a href=...>` не вставляет произвольную разметку;
- не больше MAX_MEMBERS участников (самые недавно активные), чтобы чат на 10 000 человек
  не получил полчаса спама;
- кулдаун на чат (Redis SET NX EX): повторный вызов во время рассылки отклоняется;
- рассылка идёт фоновой задачей, flood wait (TelegramRetryAfter) пережидается,
  другие ошибки Telegram останавливают рассылку с записью в лог;
- тексты — в locales/.
"""
from __future__ import annotations

import asyncio
import html
import logging
from typing import Awaitable, Callable, Sequence

from aiogram import Router
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select

from bot.config import settings
from bot.database import SessionFactory
from bot.database.models import ChatUser
from bot.filters.roles import HasRole
from bot.services.cache import redis
from bot.utils.i18n import t

logger = logging.getLogger(__name__)

router = Router(name="tag_settings")

BATCH_SIZE = 5
BATCH_DELAY_SEC = 1.0
MAX_MEMBERS = 500
MAX_NOTE_LENGTH = 1000
# Покрывает время рассылки MAX_MEMBERS (~100 сообщений) с запасом.
COOLDOWN_SEC = 600
MAX_RETRIES = 3
DEFAULT_NOTE = "\U0001f4e2"

SendFunc = Callable[[str], Awaitable[object]]

# Ссылки на фоновые задачи: иначе сборщик мусора может прервать незавершённую рассылку.
_tasks: set[asyncio.Task] = set()
# Вынесено, чтобы тесты могли не ждать реальные паузы.
_sleep = asyncio.sleep


def cooldown_key(chat_id: int) -> str:
    return f"tagall:{chat_id}"


def build_note(args: str | None) -> str:
    """Текст админа, безопасный для parse_mode=HTML."""
    note = (args or "").strip()[:MAX_NOTE_LENGTH]
    return html.escape(note) if note else DEFAULT_NOTE


def mention_batches(user_ids: Sequence[int], size: int = BATCH_SIZE) -> list[str]:
    return [
        " ".join(f'<a href="tg://user?id={uid}">\u2060</a>' for uid in user_ids[i:i + size])
        for i in range(0, len(user_ids), size)
    ]


async def _send_with_retry(send: SendFunc, text: str) -> bool:
    for _ in range(MAX_RETRIES):
        try:
            await send(text)
            return True
        except TelegramRetryAfter as exc:
            logger.warning("tagall: flood wait %s s", exc.retry_after)
            await _sleep(exc.retry_after)
    return False


async def send_mentions(send: SendFunc, note: str, user_ids: Sequence[int]) -> int:
    """Отправляет упоминания пачками. Возвращает число отправленных сообщений."""
    sent = 0
    for index, mentions in enumerate(mention_batches(user_ids)):
        if index:
            await _sleep(BATCH_DELAY_SEC)
        try:
            delivered = await _send_with_retry(send, f"{note} {mentions}")
        except TelegramAPIError as exc:
            logger.warning("tagall stopped after %d messages: %s", sent, exc)
            break
        if not delivered:
            logger.warning("tagall stopped after %d messages: flood wait did not end", sent)
            break
        sent += 1
    return sent


async def load_member_ids(chat_id: int) -> list[int]:
    """Участники в чате (вышедших не тегаем, issue #47), сначала самые недавно активные."""
    async with SessionFactory() as session:
        rows = await session.execute(
            select(ChatUser.user_id)
            .where(ChatUser.chat_id == chat_id, ChatUser.left_at.is_(None))
            .order_by(ChatUser.last_seen_at.desc().nulls_last())
            .limit(MAX_MEMBERS)
        )
        return list(rows.scalars().all())


def _on_task_done(task: asyncio.Task) -> None:
    _tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("tagall task failed", exc_info=task.exception())


@router.message(Command("tagall"), HasRole("admin"))
async def tag_all(message: Message, command: CommandObject, lang: str | None = None) -> None:
    lang = lang or settings.default_lang
    chat_id = message.chat.id

    # Ключ ставится до чтения БД: два одновременных вызова не запустят две рассылки.
    if not await redis.set(cooldown_key(chat_id), 1, ex=COOLDOWN_SEC, nx=True):
        await message.answer(t(lang, "tagall_busy", minutes=COOLDOWN_SEC // 60))
        return

    user_ids = await load_member_ids(chat_id)
    if not user_ids:
        await redis.delete(cooldown_key(chat_id))
        await message.answer(t(lang, "tagall_empty"))
        return

    note = build_note(command.args)

    async def send(text: str) -> object:
        return await message.answer(text, parse_mode="HTML")

    task = asyncio.create_task(send_mentions(send, note, user_ids))
    _tasks.add(task)
    task.add_done_callback(_on_task_done)
