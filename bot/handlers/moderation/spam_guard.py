"""
Антиспам, часть 2 (issue #14): база CAS и правила для новичков.

CAS (Combot Anti-Spam):
- при входе в чат аккаунт из базы CAS сразу банится (вызов из service_events);
- сообщение от аккаунта из базы удаляется, автор банится (moderation_pipeline).

Новички — те, кто вошёл в чат при боте. Первые N сообщений в течение H часов после входа
проверяются строже:
- любая ссылка не из белого списка (/allowlink) — спам;
- упоминание @канала/пользователя или пересылка — спам, если у аккаунта нет ни username,
  ни аватара (типичный признак бота-рекламщика).
Спам удаляется и, если задано (/newcomers), наказывается. Спам-сообщения не засчитываются
в N: доверие зарабатывается только чистыми сообщениями. Правка сообщения проверяется,
но не считается новым сообщением.

Всё это работает, только пока включён антиспам (/antispam).
"""
from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, User

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.handlers.moderation.link_settings import extract_links, is_whitelisted, link_host
from bot.services.cache import redis
from bot.services.cas import is_cas_banned
from bot.services.chat_lang import get_chat_lang
from bot.services.moderation_actions import (
    DEFAULT_MUTE_MINUTES, MAX_MUTE_MINUTES, apply_sanction, parse_auto_action,
)
from bot.services.settings_service import update_settings
from bot.utils.i18n import t
from bot.utils.parsing import bounded_int
from bot.utils.permissions import is_privileged
from bot.utils.telegram import delete_message_safely, message_entities

router = Router(name="spam_guard")
logger = logging.getLogger(__name__)

NEWCOMER_ACTIONS = ("delete", "warn", "mute", "kick", "ban", "off")
DEFAULT_NEWCOMER_MESSAGES = 3
DEFAULT_NEWCOMER_HOURS = 24
MAX_NEWCOMER_MESSAGES = 20
MAX_NEWCOMER_HOURS = 24 * 7


def newcomer_key(chat_id: int, user_id: int) -> str:
    return f"newcomer:{chat_id}:{user_id}"


def newcomer_limits(cfg: dict) -> tuple[int, int]:
    """(сколько первых сообщений проверять, сколько часов после входа)."""
    messages = bounded_int(cfg.get("messages"), DEFAULT_NEWCOMER_MESSAGES, 1, MAX_NEWCOMER_MESSAGES)
    hours = bounded_int(cfg.get("hours"), DEFAULT_NEWCOMER_HOURS, 1, MAX_NEWCOMER_HOURS)
    return messages, hours


def _antispam_on(chat_settings: dict) -> bool:
    return bool(chat_settings.get("antispam", {}).get("enabled"))


def cas_enabled(chat_settings: dict) -> bool:
    return _antispam_on(chat_settings) and chat_settings.get("antispam", {}).get("cas", True) is not False


def newcomer_action(chat_settings: dict) -> str:
    if not _antispam_on(chat_settings):
        return "off"
    action = chat_settings.get("newcomers", {}).get("action", "delete")
    return action if action in NEWCOMER_ACTIONS else "delete"


def _is_real_user(message: Message) -> bool:
    """Живой автор, а не бот и не сообщение от имени канала/группы."""
    return message.from_user is not None and not message.from_user.is_bot and message.sender_chat is None


# --------------------------------------------------------------------------- #
# CAS
# --------------------------------------------------------------------------- #

async def check_cas(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    if not cas_enabled(chat_settings) or is_privileged(chat_user_role) or not _is_real_user(message):
        return False
    if not await is_cas_banned(message.from_user.id):
        return False
    await delete_message_safely(message)
    lang = await get_chat_lang(message.chat.id)
    await apply_sanction(message.bot, message.chat.id, message.from_user.id, "ban",
                         t(lang, "cas_reason"), 0, lang=lang)
    return True


async def ban_cas_members(bot: Bot, chat_id: int, chat_settings: dict, members: list[User],
                          lang: str = "ru") -> list[int]:
    """Банит вошедших из базы CAS. Возвращает id забаненных: им не нужны капча и приветствие."""
    if not cas_enabled(chat_settings):
        return []
    banned: list[int] = []
    for member in members:
        if member.is_bot or not await is_cas_banned(member.id):
            continue
        error = await apply_sanction(bot, chat_id, member.id, "ban", t(lang, "cas_reason"), 0, lang=lang)
        if error is None:
            banned.append(member.id)
        else:
            logger.warning("Cannot ban CAS-listed user %s in chat %s: %s", member.id, chat_id, error)
    return banned


# --------------------------------------------------------------------------- #
# Новички
# --------------------------------------------------------------------------- #

async def mark_newcomers(chat_id: int, chat_settings: dict, members: list[User]) -> None:
    """Вызывается при входе: значение ключа — сколько сообщений новичок уже написал."""
    if newcomer_action(chat_settings) == "off":
        return
    _, hours = newcomer_limits(chat_settings.get("newcomers", {}))
    for member in members:
        await redis.set(newcomer_key(chat_id, member.id), 0, ex=hours * 3600)


def foreign_links(message: Message, whitelist: list[str]) -> list[str]:
    return [link for link in extract_links(message) if not is_whitelisted(link_host(link), whitelist)]


def has_promo(message: Message) -> bool:
    """Упоминание или пересылка — так рекламируют каналы без прямых ссылок."""
    if getattr(message, "forward_origin", None) is not None:
        return True
    return any(e.type in ("mention", "text_mention") for e in message_entities(message))


async def has_public_profile(bot: Bot, user: User) -> bool:
    """Есть username или аватар. При ошибке Telegram считаем профиль нормальным."""
    if user.username:
        return True
    try:
        photos = await bot.get_user_profile_photos(user.id, limit=1)
    except TelegramAPIError as exc:
        logger.warning("Cannot get profile photos of %s: %s", user.id, exc)
        return True
    return photos.total_count > 0


async def _is_newcomer_spam(message: Message, chat_settings: dict) -> bool:
    whitelist = chat_settings.get("link_settings", {}).get("whitelist", [])
    if foreign_links(message, whitelist):
        return True
    return has_promo(message) and not await has_public_profile(message.bot, message.from_user)


async def check_newcomer_spam(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    action = newcomer_action(chat_settings)
    if action == "off" or is_privileged(chat_user_role) or not _is_real_user(message):
        return False

    key = newcomer_key(message.chat.id, message.from_user.id)
    raw = await redis.get(key)
    if raw is None:
        return False  # старый участник или новичок, уже заслуживший доверие

    is_edit = message.edit_date is not None
    count = int(raw) if is_edit else await redis.incr(key)
    max_messages, _ = newcomer_limits(chat_settings.get("newcomers", {}))
    if count > max_messages:
        await redis.delete(key)
        return False

    if not await _is_newcomer_spam(message, chat_settings):
        if count >= max_messages:
            await redis.delete(key)
        return False

    if not is_edit:
        await redis.incr(key, -1)  # спам не приближает к доверию
    await delete_message_safely(message)
    if action != "delete":
        lang = await get_chat_lang(message.chat.id)
        minutes = None
        if action == "mute":
            minutes = bounded_int(chat_settings.get("newcomers", {}).get("mute_minutes"),
                                  DEFAULT_MUTE_MINUTES, 1, MAX_MUTE_MINUTES)
        await apply_sanction(message.bot, message.chat.id, message.from_user.id, action,
                             t(lang, "newcomer_reason"), 0, minutes, lang=lang)
    return True


# --------------------------------------------------------------------------- #
# Команды
# --------------------------------------------------------------------------- #

@router.message(Command("cas"), HasRole("admin"))
async def toggle_cas(message: Message, command: CommandObject, lang: str = "ru") -> None:
    arg = (command.args or "").strip().lower()
    if arg not in ("on", "off"):
        await message.answer(t(lang, "cas_usage"))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "antispam", {"cas": arg == "on"})
    await message.answer(t(lang, "cas_on" if arg == "on" else "cas_off"))


@router.message(Command("newcomers"), HasRole("admin"))
async def set_newcomer_action(message: Message, command: CommandObject, lang: str = "ru") -> None:
    """/newcomers delete | warn | kick | ban | off | mute [МИНУТ]"""
    values = parse_auto_action(command.args, NEWCOMER_ACTIONS)
    if values is None:
        await message.answer(t(lang, "newcomers_usage", messages=DEFAULT_NEWCOMER_MESSAGES,
                               hours=DEFAULT_NEWCOMER_HOURS))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "newcomers", values)
    await message.answer(t(lang, "newcomers_set", action=values["action"]))
