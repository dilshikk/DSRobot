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

issue #12: ответы и причина санкции — на языке чата.
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
from bot.services.chat_lang import get_chat_lang
from bot.services.moderation_actions import apply_sanction, parse_auto_action
from bot.services.settings_service import update_settings
from bot.utils.i18n import t
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


def words_list_text(lang: str, title: str, mode: str, words: list[str]) -> str:
    body = ", ".join(escape(w) for w in sorted(words)) if words else t(lang, "words_list_empty")
    return t(lang, "words_list", title=escape(title), mode=mode, body=body)


def word_mode_text(lang: str, mode: str) -> str:
    label_key = "wordmode_substring" if mode == MATCH_SUBSTRING else "wordmode_word"
    return t(lang, "wordmode_set", label=t(lang, label_key))


@router.message(Command("addword"), HasRole("admin"))
async def add_word(message: Message, command: CommandObject, lang: str = "ru") -> None:
    word = _clean_word(command.args)
    if not word:
        await message.answer(t(lang, "words_add_usage"))
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
        await message.answer(t(lang, "word_exists"))
        return
    await message.answer(t(lang, "word_added"))


@router.message(Command("delword"), HasRole("admin"))
async def del_word(message: Message, command: CommandObject, lang: str = "ru") -> None:
    word = _clean_word(command.args)
    if not word:
        await message.answer(t(lang, "words_del_usage"))
        return
    async with SessionFactory() as session:
        result = await session.execute(
            delete(BannedWord).where(BannedWord.chat_id == message.chat.id, BannedWord.word == word)
        )
        await session.commit()
    await _invalidate(message.chat.id)
    if result.rowcount == 0:
        await message.answer(t(lang, "word_missing"))
        return
    await message.answer(t(lang, "word_deleted"))


@router.message(Command("words"), HasRole("admin"))
async def list_words(message: Message, chat_settings: dict | None = None, lang: str = "ru") -> None:
    """Список не показываем в общем чате: он подсказывает, как обойти фильтр."""
    words = await get_banned_words(message.chat.id)
    mode = (chat_settings or {}).get("banned_words", {}).get("match", MATCH_WORD)
    text = words_list_text(lang, message.chat.title or str(message.chat.id), mode, words)

    if message.from_user is None:
        # Анонимный админ: лички нет, отвечаем в чат.
        await message.answer(text)
        return
    try:
        await message.bot.send_message(message.from_user.id, text)
        await message.answer(t(lang, "words_sent_dm"))
    except TelegramAPIError:
        await message.answer(t(lang, "words_dm_failed"))


@router.message(Command("wordmode"), HasRole("admin"))
async def set_word_mode(message: Message, command: CommandObject, lang: str = "ru") -> None:
    mode = (command.args or "").strip().lower()
    if mode not in MATCH_MODES:
        await message.answer(t(lang, "wordmode_usage"))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "banned_words", {"match": mode})
    await message.answer(word_mode_text(lang, mode))


WORD_ACTIONS = ("delete", *SANCTION_ACTIONS)


@router.message(Command("wordaction"), HasRole("admin"))
async def set_word_action(message: Message, command: CommandObject, lang: str = "ru") -> None:
    values = parse_auto_action(command.args, WORD_ACTIONS)
    if values is None:
        await message.answer(t(lang, "word_action_usage"))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "banned_words", values)
    await message.answer(t(lang, "word_action_set", action=values["action"]))


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
        # Проверки из moderation_pipeline не получают handler data, язык берём из кэша.
        lang = await get_chat_lang(message.chat.id)
        # Мут — на срок, а не навсегда (issue #41).
        duration = int(cfg.get("mute_minutes", 60)) if action == "mute" else None
        await apply_sanction(message.bot, message.chat.id, message.from_user.id, action,
                             t(lang, "banned_word_reason"), 0, duration, lang=lang)
    return True
