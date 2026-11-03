"""Members management: список участников, поиск, массовая чистка неактивных.

issue #47: активность считается по чату (ChatUser.last_seen_at), а не по глобальному
User.last_seen; санкции не обновляют активность; вышедшие участники не попадают в список.
"""
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command, CommandObject
from sqlalchemy import func, select

from bot.database import SessionFactory
from bot.database.models import ChatUser, User
from bot.filters.roles import HasRole
from bot.utils.parsing import parse_int

router = Router(name="members_management")

MAX_INACTIVE_DAYS = 3650
INACTIVE_LIMIT = 50


@router.message(Command("members"), HasRole("admin"))
async def members_count(message) -> None:
    count = await message.bot.get_chat_member_count(message.chat.id)
    await message.answer(f"\U0001f465 Участников в чате: {count}")


def inactive_members_query(chat_id: int, threshold: datetime, limit: int = INACTIVE_LIMIT):
    # Кто ни разу не писал после обновления — считаем активным с момента вступления.
    last_active = func.coalesce(ChatUser.last_seen_at, ChatUser.joined_at)
    return (
        select(User.id, User.username, last_active.label("last_active"))
        .join(ChatUser, ChatUser.user_id == User.id)
        .where(ChatUser.chat_id == chat_id, ChatUser.left_at.is_(None), last_active < threshold)
        .order_by(last_active)
        .limit(limit)
    )


@router.message(Command("inactive"), HasRole("admin"))
async def list_inactive(message, command: CommandObject) -> None:
    """Показывает участников, не писавших в этом чате дольше N дней (по умолчанию 30)."""
    days = parse_int(command.args, 1, MAX_INACTIVE_DAYS) if command.args else 30
    if days is None:
        await message.answer(f"Использование: /inactive [дней, 1-{MAX_INACTIVE_DAYS}]")
        return
    threshold = datetime.now(timezone.utc) - timedelta(days=days)

    async with SessionFactory() as session:
        rows = (await session.execute(inactive_members_query(message.chat.id, threshold))).all()

    if not rows:
        await message.answer(f"Нет участников, неактивных более {days} дн.")
        return
    lines = [f"• {u.username or u.id} — последний раз {u.last_active:%Y-%m-%d}" for u in rows]
    await message.answer(f"Неактивны > {days} дн. ({len(rows)}):\n" + "\n".join(lines))
