"""Blocks settings: forwards / links / usernames-mentions / bots / inline-queries.

Проверка пересылок вызывается из moderation_pipeline, блок ботов — из service_events (issue #1).
Ответы — на языке чата (issue #12).
"""
import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, User

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings
from bot.utils.i18n import t
from bot.utils.permissions import is_privileged
from bot.handlers.moderation.link_settings import extract_links
from bot.utils.telegram import delete_message_safely, is_rights_error, message_entities, notify_missing_rights

router = Router(name="blocks")
logger = logging.getLogger(__name__)

# Кортеж, а не set: порядок в подсказке «Использование» должен быть стабильным.
TOGGLES = ("forwards", "links", "usernames", "bots", "inline")


async def _set_block(message: Message, command: CommandObject, lang: str, enabled: bool) -> None:
    key = (command.args or "").strip().lower()
    if key not in TOGGLES:
        usage_key = "block_usage" if enabled else "unblock_usage"
        await message.answer(t(lang, usage_key, options=" | ".join(TOGGLES)))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "blocks", {key: enabled})
    await message.answer(t(lang, "block_on" if enabled else "block_off", name=key))


@router.message(Command("block"), HasRole("admin"))
async def block_toggle(message: Message, command: CommandObject, lang: str = "ru") -> None:
    await _set_block(message, command, lang, enabled=True)


@router.message(Command("unblock"), HasRole("admin"))
async def unblock_toggle(message: Message, command: CommandObject, lang: str = "ru") -> None:
    await _set_block(message, command, lang, enabled=False)


def _is_forwarded(message: Message) -> bool:
    # В Bot API 7.0+ информация о пересылке лежит в forward_origin (forward_from* устарели).
    return bool(getattr(message, "forward_origin", None) or getattr(message, "forward_date", None))


async def check_forward_block(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    if not chat_settings.get("blocks", {}).get("forwards") or is_privileged(chat_user_role):
        return False
    if not _is_forwarded(message):
        return False
    await delete_message_safely(message)
    return True


# links/usernames/inline раньше только сохранялись в настройках, но нигде не проверялись (issue #43).
CONTENT_BLOCKS = {
    "links": lambda m: bool(extract_links(m)),
    "usernames": lambda m: any(e.type in ("mention", "text_mention") for e in message_entities(m)),
    "inline": lambda m: m.via_bot is not None,
}


async def check_content_blocks(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    cfg = chat_settings.get("blocks", {})
    if is_privileged(chat_user_role) or not any(cfg.get(k) and has(message) for k, has in CONTENT_BLOCKS.items()):
        return False
    await delete_message_safely(message)
    return True


async def kick_blocked_bots(bot: Bot, chat_id: int, chat_settings: dict, members: list[User]) -> list[User]:
    """Удаляет добавленных ботов (если включено) и возвращает оставшихся участников."""
    if not chat_settings.get("blocks", {}).get("bots"):
        return list(members)
    remaining: list[User] = []
    for member in members:
        # Не трогаем самого себя — иначе бот выкинет себя при добавлении в группу.
        if member.is_bot and member.id != bot.id:
            try:
                await bot.ban_chat_member(chat_id, member.id)
                await bot.unban_chat_member(chat_id, member.id)
                continue
            except TelegramBadRequest as exc:
                logger.warning("Cannot kick bot %s from chat %s: %s", member.id, chat_id, exc)
                if is_rights_error(exc):
                    # Ключ локали: notify_missing_rights сам подставит язык чата.
                    await notify_missing_rights(bot, chat_id, "rights_action_kick_bots")
            except TelegramAPIError as exc:
                logger.warning("Cannot kick bot %s from chat %s: %s", member.id, chat_id, exc)
        remaining.append(member)
    return remaining
