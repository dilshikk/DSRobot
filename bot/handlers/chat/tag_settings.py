"""Tag settings: @all / рассылка тега всем участникам чата (с батчингом, чтобы не упереться в rate-limit).
Ответы — на языке чата (issue #12)."""
import asyncio
from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import ChatUser
from bot.filters.roles import HasRole
from bot.utils.i18n import t

router = Router(name="tag_settings")

BATCH_SIZE = 5


@router.message(Command("tagall"), HasRole("admin"))
async def tag_all(message, command: CommandObject, lang: str = "ru") -> None:
    async with SessionFactory() as session:
        user_ids = (await session.execute(
            select(ChatUser.user_id).where(ChatUser.chat_id == message.chat.id)
        )).scalars().all()

    if not user_ids:
        await message.answer(t(lang, "tagall_empty"))
        return

    # Текст пишет админ, а сообщение уходит с parse_mode=HTML — экранируем.
    note = escape(command.args) if command.args else "\U0001f4e2"
    for i in range(0, len(user_ids), BATCH_SIZE):
        batch = user_ids[i:i + BATCH_SIZE]
        mentions = " ".join(f'<a href="tg://user?id={uid}">\u2060</a>' for uid in batch)
        await message.answer(f"{note} {mentions}", parse_mode="HTML")
        await asyncio.sleep(1)
