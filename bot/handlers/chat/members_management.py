"""Members management: список участников, поиск, массовая чистка неактивных (по last_seen)."""
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command, CommandObject
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import ChatUser, User
from bot.filters.roles import HasRole

router = Router(name="members_management")


@router.message(Command("members"), HasRole("admin"))
async def members_count(message) -> None:
    count = await message.bot.get_chat_member_count(message.chat.id)
    await message.answer(f"\U0001f465 Участников в чате: {count}")


@router.message(Command("inactive"), HasRole("admin"))
async def list_inactive(message, command: CommandObject) -> None:
    """Показывает пользователей, не писавших дольше N дней (по умолчанию 30)."""
    days = int(command.args) if command.args and command.args.isdigit() else 30
    threshold = datetime.now(timezone.utc) - timedelta(days=days)

    async with SessionFactory() as session:
        rows = (await session.execute(
            select(User.id, User.username, User.last_seen)
            .join(ChatUser, ChatUser.user_id == User.id)
            .where(ChatUser.chat_id == message.chat.id, User.last_seen < threshold)
            .limit(50)
        )).all()

    if not rows:
        await message.answer(f"Нет участников, неактивных более {days} дн.")
        return
    lines = [f"• {u.username or u.id} — последний раз {u.last_seen:%Y-%m-%d}" for u in rows]
    await message.answer(f"Неактивны > {days} дн. ({len(rows)}):\n" + "\n".join(lines))
