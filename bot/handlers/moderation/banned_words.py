"""
Banned words: /addword /delword /words /wordmode + проверка входящих сообщений
(вызывается из moderation_pipeline).

issue #8:
- сравнение по границам слов с нормализацией гомоглифов (см. utils/text_match.py),
  режим «подстрока» включается командой /wordmode;
- список слов кэшируется в Redis и сбрасывается при /addword и /delword;
- проверяются и подписи к медиа (caption);
- повторный /addword не падает (ON CONFLICT DO NOTHING);
- /words доступна только админам, список отправляется в личку.
"""
from __future__ import annotations

import logging
from html import escape

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bot.database import SessionFactory
from bot.database.models import BannedWord
from bot.filters.roles import HasRole
from bot.services.cache import get_json, redis, set_json
from bot.services.moderation_actions import apply_sanction
from bot.services.settings_service import update_settings
from bot.utils.permissions import is_privileged
from bot.utils.text_match import MATCH_MODES, MATCH_SUBSTRING, MATCH_WORD, find_banned

logger = logging.getLogger(__name__)

router = Router(name="banned_words")

WORDS_CACHE_TTL = 600
MAX_WORD_LENGTH = 255
SANCTION_ACTIONS = ("warn", "mute", "kick", "ban")


def _cache_key(chat_id: int) -> str:
    return f"banned_words:{chat_id}"


async def get_banned_words(chat_id: int) -> list[str]:
    cached = await get_json(_cache_key(chat_id))
    if cached is not None:
        return cached
    async with SessionFactory() as session:
        words = list((await session.execute(
            select(BannedWord.word).where(BannedWord.chat_id == chat_id)
        )).scalars().all())
    await set_json(_cache_key(chat_id), words, ex=WORDS_CACHE_TTL)
    return words


async def _invalidate(chat_id: int) -> None:
    await redis.delete(_cache_key(chat_id))


def _clean_word(raw: str | None) -> str:
    return (raw or "").strip().lower()[:MAX_WORD_LENGTH]


@router.message(Command("addword"), HasRole("admin"))
async def add_word(message: Message, command: CommandObject) -> None:
    word = _clean_word(command.args)
    if not word:
        await message.answer("Использование: /addword СЛОВО")
        return
    async with SessionFactory() as session:
        result = await session.execute(
            pg_insert(BannedWord)
            .values(chat_id=message.chat.id, word=word)
            .on_conflict_do_nothing(constraint="uq_chat_word")
        )
        await session.commit()
    await _invalidate(message.chat.id)
    if result.rowcount == 0:
        await message.answer("Это слово уже в чёрном списке.")
        return
    await message.answer("\u2705 Слово добавлено в чёрный список.")


@router.message(Command("delword"), HasRole("admin"))
async def del_word(message: Message, command: CommandObject) -> None:
    word = _clean_word(command.args)
    if not word:
        await message.answer("Использование: /delword СЛОВО")
        return
    async with SessionFactory() as session:
        result = await session.execute(
            delete(BannedWord).where(BannedWord.chat_id == message.chat.id, BannedWord.word == word)
        )
        await session.commit()
    await _invalidate(message.chat.id)
    if result.rowcount == 0:
        await message.answer("Такого слова нет в чёрном списке.")
        return
    await message.answer("\u2705 Слово удалено из чёрного списка.")


@router.message(Command("words"), HasRole("admin"))
async def list_words(message: Message, chat_settings: dict | None = None) -> None:
    """Список не показываем в общем чате: он подсказывает, как обойти фильтр."""
    words = await get_banned_words(message.chat.id)
    mode = (chat_settings or {}).get("banned_words", {}).get("match", MATCH_WORD)
    title = escape(message.chat.title or str(message.chat.id))
    body = ", ".join(escape(w) for w in sorted(words)) if words else "список пуст"
    text = f"Запрещённые слова в «{title}» (режим: {mode}):\n{body}"

    if message.from_user is None:
        # Анонимный админ: лички нет, отвечаем в чат.
        await message.answer(text)
        return
    try:
        await message.bot.send_message(message.from_user.id, text)
        await message.answer("Список отправлен вам в личные сообщения.")
    except TelegramAPIError:
        await message.answer("Не удалось написать вам в личку. Откройте диалог с ботом, нажмите /start и повторите.")


@router.message(Command("wordmode"), HasRole("admin"))
async def set_word_mode(message: Message, command: CommandObject) -> None:
    mode = (command.args or "").strip().lower()
    if mode not in MATCH_MODES:
        await message.answer(
            "Использование: /wordmode word | substring\n"
            "word — только целое слово (по умолчанию), substring — любое вхождение."
        )
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "banned_words", {"match": mode})
    label = "любое вхождение" if mode == MATCH_SUBSTRING else "только целое слово"
    await message.answer(f"\u2705 Поиск запрещённых слов: {label}.")


async def check_banned_words(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    text = message.text or message.caption
    if not text or is_privileged(chat_user_role) or message.from_user is None:
        return False
    words = await get_banned_words(message.chat.id)
    cfg = chat_settings.get("banned_words", {})
    if not find_banned(text, words, cfg.get("match", MATCH_WORD)):
        return False

    try:
        await message.delete()
    except TelegramAPIError as exc:
        logger.warning("Cannot delete banned-word message in chat %s: %s", message.chat.id, exc)

    action = cfg.get("action", "delete")
    if action in SANCTION_ACTIONS:
        await apply_sanction(message.bot, message.chat.id, message.from_user.id, action,
                             "Запрещённое слово", 0)
    return True
