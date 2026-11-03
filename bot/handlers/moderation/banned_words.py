"""Banned words: /addword /delword /words + проверка входящих сообщений (из moderation_pipeline)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select, delete

from bot.database import SessionFactory
from bot.database.models import BannedWord
from bot.filters.roles import HasRole
from bot.services.moderation_actions import apply_sanction
from bot.utils.permissions import is_privileged

router = Router(name="banned_words")


@router.message(Command("addword"), HasRole("admin"))
async def add_word(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Использование: /addword <слово>")
        return
    async with SessionFactory() as session:
        session.add(BannedWord(chat_id=message.chat.id, word=command.args.strip().lower()))
        await session.commit()
    await message.answer("\u2705 Слово добавлено в чёрный список.")


@router.message(Command("delword"), HasRole("admin"))
async def del_word(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Использование: /delword <слово>")
        return
    async with SessionFactory() as session:
        await session.execute(
            delete(BannedWord).where(BannedWord.chat_id == message.chat.id, BannedWord.word == command.args.strip().lower())
        )
        await session.commit()
    await message.answer("\u2705 Слово удалено из чёрного списка.")


@router.message(Command("words"))
async def list_words(message: Message) -> None:
    async with SessionFactory() as session:
        rows = (await session.execute(select(BannedWord.word).where(BannedWord.chat_id == message.chat.id))).scalars().all()
    await message.answer("Запрещённые слова: " + (", ".join(rows) if rows else "список пуст"))


async def check_banned_words(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    if not message.text or is_privileged(chat_user_role):
        return False
    async with SessionFactory() as session:
        words = (await session.execute(select(BannedWord.word).where(BannedWord.chat_id == message.chat.id))).scalars().all()
    if not words:
        return False
    text_lower = message.text.lower()
    if not any(w in text_lower for w in words):
        return False

    action = chat_settings.get("banned_words", {}).get("action", "delete")
    try:
        await message.delete()
    except Exception:
        pass
    if action != "delete":
        await apply_sanction(message.bot, message.chat.id, message.from_user.id, action,
                              "Запрещённое слово", 0)
    return True
