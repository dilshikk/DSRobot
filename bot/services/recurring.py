"""
Периодические рассылки (issue #10).

Источник правды — таблица recurring_messages. Задача в планировщике хранит только
id рассылки: текст, бот и активность читаются из БД при каждом запуске. При старте
все активные рассылки пересоздаются с актуальным часовым поясом чата, а задачи
удалённых рассылок убираются.
"""
from __future__ import annotations

import logging

from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import Chat, RecurringMessage
from bot.services.bot_registry import get_bot
from bot.services.scheduler import build_cron_trigger, remove_job, schedule_cron, scheduler

logger = logging.getLogger(__name__)

JOB_PREFIX = "recurring:"
CRON_FIELDS = 5
# Telegram на телефонах часто подменяет прямые кавычки на «ёлочки» или “лапки”.
_QUOTES = {'"': '"', "'": "'", "\u201c": "\u201d", "\u00ab": "\u00bb"}


def job_id(message_id: int) -> str:
    return f"{JOB_PREFIX}{message_id}"


def parse_recurring_args(raw: str | None) -> tuple[str, str] | None:
    """
    Разбирает аргументы /addrecurring. Поддерживает оба варианта:
      "0 9 * * *" Доброе утро!
      0 9 * * * Доброе утро!
    Возвращает (cron, текст) или None, если формат или cron неверные.
    """
    raw = (raw or "").strip()
    if not raw:
        return None

    if raw[0] in _QUOTES:
        end = raw.find(_QUOTES[raw[0]], 1)
        if end == -1:
            return None
        cron, text = raw[1:end].strip(), raw[end + 1:].strip()
    else:
        parts = raw.split(maxsplit=CRON_FIELDS)
        if len(parts) <= CRON_FIELDS:
            return None
        cron, text = " ".join(parts[:CRON_FIELDS]), parts[CRON_FIELDS].strip()

    if not cron or not text:
        return None
    try:
        build_cron_trigger(cron)
    except ValueError:
        return None
    return cron, text


def schedule_recurring(row: RecurringMessage, utc_offset: int) -> None:
    schedule_cron(send_recurring, row.cron_expression, job_id=job_id(row.id),
                  utc_offset=utc_offset, message_id=row.id)


async def send_recurring(message_id: int) -> None:
    """Функция задачи. Хранится в Redis по ссылке "модуль:имя" — не переименовывайте."""
    async with SessionFactory() as session:
        row = await session.get(RecurringMessage, message_id)
    if row is None or not row.is_active:
        remove_job(job_id(message_id))
        return

    bot = get_bot(row.bot_id)
    if bot is None:
        logger.warning("Рассылка #%s: бот %s не запущен, пропускаю", message_id, row.bot_id)
        return
    try:
        await bot.send_message(row.chat_id, row.text)
    except TelegramAPIError as exc:
        logger.warning("Рассылка #%s в чат %s не отправлена: %s", message_id, row.chat_id, exc)


async def _active_rows(chat_id: int | None = None) -> list[tuple[RecurringMessage, int]]:
    query = (
        select(RecurringMessage, Chat.utc_offset)
        .outerjoin(Chat, Chat.id == RecurringMessage.chat_id)
        .where(RecurringMessage.is_active.is_(True))
    )
    if chat_id is not None:
        query = query.where(RecurringMessage.chat_id == chat_id)
    async with SessionFactory() as session:
        return [(row, offset or 0) for row, offset in (await session.execute(query)).all()]


def _schedule_rows(rows: list[tuple[RecurringMessage, int]]) -> set[str]:
    scheduled: set[str] = set()
    for row, offset in rows:
        try:
            schedule_recurring(row, offset)
        except ValueError:
            logger.error("Рассылка #%s: неверный cron %r, пропускаю", row.id, row.cron_expression)
            continue
        scheduled.add(job_id(row.id))
    return scheduled


async def restore_recurring_jobs() -> int:
    """Вызывается при старте после запуска планировщика. Возвращает число активных рассылок."""
    scheduled = _schedule_rows(await _active_rows())
    for job in scheduler.get_jobs():
        if job.id.startswith(JOB_PREFIX) and job.id not in scheduled:
            job.remove()
    return len(scheduled)


async def reschedule_chat(chat_id: int) -> int:
    """Пересоздаёт рассылки чата, например после смены часового пояса (/setutc)."""
    return len(_schedule_rows(await _active_rows(chat_id)))
