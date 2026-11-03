"""Recurring messages: cron-рассылки в чат (объявления, напоминания о правилах и т.п.)."""
from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import RecurringMessage
from bot.filters.roles import HasRole
from bot.services.scheduler import schedule_cron

router = Router(name="recurring_messages")

_bot_ref: Bot | None = None


def bind_bot(bot: Bot) -> None:
    global _bot_ref
    _bot_ref = bot


async def _send_recurring(chat_id: int, text: str) -> None:
    if _bot_ref:
        try:
            await _bot_ref.send_message(chat_id, text)
        except Exception:
            pass


@router.message(Command("addrecurring"), HasRole("admin"))
async def add_recurring(message, command: CommandObject) -> None:
    """Использование: /addrecurring <cron> <текст>, например: /addrecurring "0 9 * * *" Доброе утро!"""
    if not command.args or " " not in command.args:
        await message.answer('Использование: /addrecurring "0 9 * * *" Текст сообщения')
        return
    cron_expr, text = command.args.split(maxsplit=1)
    cron_expr = cron_expr.strip('"')

    async with SessionFactory() as session:
        row = RecurringMessage(chat_id=message.chat.id, text=text, cron_expression=cron_expr)
        session.add(row)
        await session.commit()
        job_id = f"recurring:{row.id}"

    schedule_cron(_send_recurring, cron_expr, chat_id=message.chat.id, text=text, job_id=job_id)
    await message.answer(f"\u2705 Рассылка добавлена: `{cron_expr}`", parse_mode="Markdown")


@router.message(Command("recurring"))
async def list_recurring(message) -> None:
    async with SessionFactory() as session:
        rows = (await session.execute(
            select(RecurringMessage).where(RecurringMessage.chat_id == message.chat.id, RecurringMessage.is_active == True)  # noqa: E712
        )).scalars().all()
    if not rows:
        await message.answer("Активных рассылок нет.")
        return
    await message.answer("\n".join(f"#{r.id} `{r.cron_expression}` — {r.text[:40]}" for r in rows), parse_mode="Markdown")
