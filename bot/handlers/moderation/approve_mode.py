"""Approve mode: сообщения НОВЫХ участников фильтруются, пока их не одобрит админ.
Проверка вызывается из moderation_pipeline. Ответы — на языке чата (issue #12).

issue #50: раньше режим блокировал всех, у кого ChatUser.approved = False, то есть всех
участников чата. Теперь одобрения ждут только те, кто вступил в чат при включённом
режиме (флаг pending_approval ставится в service_events при вступлении) или кого админ
явно снял с одобрения командой /unapprove. Участник один раз получает объяснение,
почему его сообщения удаляются.
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message, User
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bot.database import SessionFactory
from bot.database.models import ChatUser
from bot.filters.roles import HasRole
from bot.services.cache import redis
from bot.services.chat_lang import get_chat_lang
from bot.services.settings_service import update_settings
from bot.services.user_service import upsert_tg_user
from bot.utils.i18n import t, toggle_text
from bot.utils.permissions import is_privileged
from bot.utils.telegram import delete_message_safely

router = Router(name="approve_mode")
logger = logging.getLogger(__name__)

# Как часто (сек) напоминать участнику, что его сообщения ждут одобрения.
NOTICE_TTL = 6 * 3600


def is_enabled(chat_settings: dict) -> bool:
    return bool(chat_settings.get("approve_mode", {}).get("enabled"))


def needs_approval(chat_user: ChatUser | None) -> bool:
    """Ждёт одобрения только тот, кого пометили при вступлении или через /unapprove."""
    return bool(chat_user and chat_user.pending_approval and not chat_user.approved)


async def _set_status(chat_id: int, user: User, approved: bool) -> None:
    async with SessionFactory() as session:
        await upsert_tg_user(session, user)
        await session.execute(
            pg_insert(ChatUser)
            .values(chat_id=chat_id, user_id=user.id, warns=0, role="member",
                    approved=approved, pending_approval=not approved)
            .on_conflict_do_update(constraint="uq_chat_user",
                                   set_={"approved": approved, "pending_approval": not approved})
        )
        await session.commit()


async def mark_new_members_pending(chat_id: int, chat_settings: dict, members: list[User]) -> None:
    """Вызывается из service_events при вступлении: новички ждут одобрения админа."""
    if not is_enabled(chat_settings):
        return
    for member in members:
        if not member.is_bot:
            await _set_status(chat_id, member, approved=False)


def _reply_target(message: Message) -> User | None:
    reply = message.reply_to_message
    # Сообщение от имени канала/анонимного админа: from_user — служебный бот, одобрять некого.
    if not reply or not reply.from_user or reply.sender_chat:
        return None
    return reply.from_user


@router.message(Command("approve"), HasRole("admin"))
async def approve_user(message: Message, lang: str = "ru") -> None:
    target = _reply_target(message)
    if target is None:
        await message.answer(t(lang, "approve_usage"))
        return
    await _set_status(message.chat.id, target, approved=True)
    await redis.delete(f"approve_notice:{message.chat.id}:{target.id}")
    await message.answer(t(lang, "approve_done"))


@router.message(Command("unapprove"), HasRole("admin"))
async def unapprove_user(message: Message, lang: str = "ru") -> None:
    target = _reply_target(message)
    if target is None:
        await message.answer(t(lang, "unapprove_usage"))
        return
    await _set_status(message.chat.id, target, approved=False)
    await message.answer(t(lang, "unapprove_done"))


@router.message(Command("approvemode"), HasRole("admin"))
async def toggle_approve_mode(message: Message, chat_settings: dict, lang: str = "ru") -> None:
    new_state = not is_enabled(chat_settings)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "approve_mode", {"enabled": new_state})
    await message.answer(toggle_text(lang, "feature_approve_mode", new_state))


async def _notify_pending(message: Message) -> None:
    """Один раз в NOTICE_TTL объясняем участнику, почему пропадают его сообщения."""
    key = f"approve_notice:{message.chat.id}:{message.from_user.id}"
    if not await redis.set(key, 1, ex=NOTICE_TTL, nx=True):
        return
    lang = await get_chat_lang(message.chat.id)
    try:
        await message.bot.send_message(
            message.chat.id, t(lang, "approve_pending_notice", mention=message.from_user.mention_html()),
            parse_mode="HTML",
        )
    except TelegramAPIError as exc:
        logger.warning("Cannot send approve notice in chat %s: %s", message.chat.id, exc)


async def check_unapproved(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    if not is_enabled(chat_settings) or is_privileged(chat_user_role) or message.from_user is None:
        return False
    async with SessionFactory() as session:
        cu = (await session.execute(
            select(ChatUser).where(ChatUser.chat_id == message.chat.id, ChatUser.user_id == message.from_user.id)
        )).scalar_one_or_none()
    if not needs_approval(cu):
        return False
    await delete_message_safely(message)
    await _notify_pending(message)
    return True
