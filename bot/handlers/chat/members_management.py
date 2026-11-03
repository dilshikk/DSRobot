"""Members management: список участников, поиск неактивных (по last_seen).
Ответы — на языке чата (issue #12)."""
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command, CommandObject
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import ChatUser, User
from bot.filters.roles import HasRole
from bot.utils.i18n import t

router = Router(name="members_management")

DEFAULT_INACTIVE_DAYS = 30


def inactive_text(lang: str, days: int, rows: list[tuple[str | int, datetime]]) -> str:
    """rows — пары (username или id, last_seen)."""
    if not rows:
        return t(lang, "inactive_none", days=days)
    lines = [t(lang, "inactive_line", name=name, date=f"{seen:%Y-%m-%d}") for name, seen in rows]
    return t(lang, "inactive_header", days=days, count=len(rows)) + "\n" + "\n".join(lines)


@router.message(Command("members"), HasRole("admin"))
async def members_count(message, lang: str = "ru") -> None:
    count = await message.bot.get_chat_member_count(message.chat.id)
    await message.answer(t(lang, "members_count", count=count))


@router.message(Command("inactive"), HasRole("admin"))
async def list_inactive(message, command: CommandObject, lang: str = "ru") -> None:
    """Показывает пользователей, не писавших дольше N дней (по умолчанию 30)."""
    days = int(command.args) if command.args and command.args.isdigit() else DEFAULT_INACTIVE_DAYS
    threshold = datetime.now(timezone.utc) - timedelta(days=days)

    async with SessionFactory() as session:
        rows = (await session.execute(
            select(User.id, User.username, User.last_seen)
            .join(ChatUser, ChatUser.user_id == User.id)
            .where(ChatUser.chat_id == message.chat.id, User.last_seen < threshold)
            .limit(50)
        )).all()

    await message.answer(inactive_text(lang, days, [(u.username or u.id, u.last_seen) for u in rows]))
