"""Tag settings: @all / рассылка тега всем участникам чата (с батчингом, чтобы не упереться в rate-limit)."""
import asyncio

from aiogram import Router
from aiogram.filters import Command, CommandObject
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import ChatUser
from bot.filters.roles import HasRole

router = Router(name="tag_settings")

BATCH_SIZE = 5


@router.message(Command("tagall"), HasRole("admin"))
async def tag_all(message, command: CommandObject) -> None:
    async with SessionFactory() as session:
        user_ids = (await session.execute(
            select(ChatUser.user_id).where(ChatUser.chat_id == message.chat.id)
        )).scalars().all()

    if not user_ids:
        await message.answer("Список участников пуст (бот ещё не индексировал чат).")
        return

    note = command.args or "\U0001f4e2"
    for i in range(0, len(user_ids), BATCH_SIZE):
        batch = user_ids[i:i + BATCH_SIZE]
        mentions = " ".join(f'<a href="tg://user?id={uid}">\u2060</a>' for uid in batch)
        await message.answer(f"{note} {mentions}", parse_mode="HTML")
        await asyncio.sleep(1)
