"""Recurring messages: cron-рассылки в чат (объявления, напоминания о правилах и т.п.).

Время в cron — по часовому поясу чата (/setutc). Логика планирования — в services/recurring.py.
Ответы — на языке чата (issue #12).
"""
from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import RecurringMessage
from bot.filters.roles import HasRole
from bot.services.recurring import job_id, parse_recurring_args, schedule_recurring
from bot.services.scheduler import remove_job
from bot.services.settings_service import get_or_create_chat
from bot.utils.i18n import t

router = Router(name="recurring_messages")


def recurring_added_text(lang: str, recurring_id: int, cron_expr: str, offset: int) -> str:
    return t(lang, "recurring_added", id=recurring_id, cron=escape(cron_expr), offset=f"{offset:+d}")


@router.message(Command("addrecurring"), HasRole("admin"))
async def add_recurring(message: Message, command: CommandObject, lang: str = "ru") -> None:
    parsed = parse_recurring_args(command.args)
    if parsed is None:
        await message.answer(t(lang, "recurring_usage"), parse_mode=None)
        return
    cron_expr, text = parsed

    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        offset = chat.utc_offset or 0
        # bot_id: рассылку в чате клона отправляет клон, а не основной бот.
        row = RecurringMessage(chat_id=message.chat.id, text=text, cron_expression=cron_expr, bot_id=message.bot.id)
        session.add(row)
        await session.commit()
        schedule_recurring(row, offset)

    await message.answer(recurring_added_text(lang, row.id, cron_expr, offset), parse_mode="HTML")


@router.message(Command("delrecurring"), HasRole("admin"))
async def del_recurring(message: Message, command: CommandObject, lang: str = "ru") -> None:
    raw = (command.args or "").strip().lstrip("#")
    if not raw.isdigit():
        await message.answer(t(lang, "delrecurring_usage"))
        return
    async with SessionFactory() as session:
        row = await session.get(RecurringMessage, int(raw))
        if row is None or row.chat_id != message.chat.id or not row.is_active:
            await message.answer(t(lang, "recurring_not_found"))
            return
        row.is_active = False
        await session.commit()
    remove_job(job_id(row.id))
    await message.answer(t(lang, "recurring_deleted", id=row.id))


@router.message(Command("recurring"))
async def list_recurring(message: Message, lang: str = "ru") -> None:
    async with SessionFactory() as session:
        rows = (await session.execute(
            select(RecurringMessage).where(
                RecurringMessage.chat_id == message.chat.id, RecurringMessage.is_active.is_(True),
            )
        )).scalars().all()
    if not rows:
        await message.answer(t(lang, "recurring_empty"))
        return
    # Текст рассылки пишет пользователь — экранируем, чтобы не сломать разметку.
    await message.answer(
        "\n".join(f"#{r.id} <code>{escape(r.cron_expression)}</code> — {escape(r.text[:40])}" for r in rows),
        parse_mode="HTML",
    )
