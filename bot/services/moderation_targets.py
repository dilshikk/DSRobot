"""
Определение цели команды модерации и проверка, что её можно наказать (issue #9).

Цель можно указать тремя способами:
- ответом на сообщение пользователя;
- числовым id: /ban 123456789 причина;
- @username: /ban @nick причина (ищется среди пользователей, которых бот уже видел).

Нельзя наказать самого бота, администратора или владельца чата, а также анонимного
админа. Сообщения от имени канала (sender_chat) наказываются через /banchannel.

issue #12: все ответы — на языке чата (аргумент lang).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape

from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMemberAdministrator, ChatMemberOwner, Message
from sqlalchemy import func, select

from bot.database import SessionFactory
from bot.database.models import User
from bot.services.moderation_actions import apply_sanction
from bot.utils.i18n import t

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Target:
    user_id: int
    mention: str  # уже безопасный HTML


@dataclass(frozen=True)
class TargetResult:
    target: Target | None
    reason: str = ""
    error: str | None = None


def _mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{escape(name)}</a>'


async def _find_by_username(username: str) -> Target | None:
    async with SessionFactory() as session:
        row = (await session.execute(
            select(User.id, User.full_name)
            .where(func.lower(User.username) == username.lower())
            .limit(1)
        )).first()
    if row is None:
        return None
    return Target(row.id, _mention(row.id, row.full_name or f"@{username}"))


def _real_reply(message: Message) -> Message | None:
    reply = message.reply_to_message
    # В форумах каждое сообщение топика "отвечает" на служебное сообщение о создании топика.
    if reply is None or reply.forum_topic_created is not None:
        return None
    return reply


async def resolve_target(message: Message, args: str | None, lang: str = "ru") -> TargetResult:
    args = (args or "").strip()
    reply = _real_reply(message)

    if reply is not None:
        if reply.sender_chat is not None:
            if reply.sender_chat.id == message.chat.id:
                return TargetResult(None, error=t(lang, "target_anonymous_admin"))
            return TargetResult(None, error=t(lang, "target_channel"))
        if reply.from_user is None:
            return TargetResult(None, error=t(lang, "target_unknown_author"))
        return TargetResult(Target(reply.from_user.id, reply.from_user.mention_html()), args)

    first, _, rest = args.partition(" ")
    rest = rest.strip()
    if not first:
        return TargetResult(None)

    if first.isdigit():
        user_id = int(first)
        return TargetResult(Target(user_id, _mention(user_id, first)), rest)

    if first.startswith("@") and len(first) > 1:
        username = first[1:]
        target = await _find_by_username(username)
        if target is None:
            return TargetResult(None, error=t(lang, "target_username_not_found", username=escape(username)))
        return TargetResult(target, rest)

    return TargetResult(None)


async def protection_error(message: Message, user_id: int, lang: str = "ru") -> str | None:
    """Возвращает причину, по которой пользователя нельзя наказать, или None."""
    if user_id == message.bot.id:
        return t(lang, "target_is_bot")
    try:
        member = await message.bot.get_chat_member(message.chat.id, user_id)
    except TelegramAPIError as exc:
        # Пользователь мог уже выйти из чата — бан по id при этом остаётся допустимым.
        logger.info("get_chat_member(%s, %s) failed: %s", message.chat.id, user_id, exc)
        return None
    if isinstance(member, (ChatMemberOwner, ChatMemberAdministrator)):
        return t(lang, "target_is_admin")
    return None


async def prepare_target(
    message: Message, args: str | None, usage: str, protect: bool = True, lang: str = "ru",
) -> tuple[Target, str] | None:
    """Находит цель и причину. Сам отвечает в чат при ошибке и возвращает None."""
    result = await resolve_target(message, args, lang)
    if result.error:
        await message.answer(f"\u26a0\ufe0f {result.error}")
        return None
    if result.target is None:
        await message.answer(t(lang, "target_missing", usage=usage))
        return None
    if protect:
        error = await protection_error(message, result.target.user_id, lang)
        if error:
            await message.answer(f"\u26a0\ufe0f {error}")
            return None
    return result.target, result.reason


async def run_sanction(
    message: Message, target: Target, action: str, reason: str = "",
    duration_minutes: int | None = None, lang: str = "ru",
) -> bool:
    """Применяет санкцию от имени автора команды. При ошибке сообщает о ней в чат."""
    actor_id = message.from_user.id if message.from_user else 0
    error = await apply_sanction(message.bot, message.chat.id, target.user_id, action, reason, actor_id,
                                 duration_minutes, lang=lang)
    if error:
        await message.answer(f"\u26a0\ufe0f {error}")
        return False
    return True
