"""
Единый обработчик служебных событий чата (issue #1).

Раньше на `F.new_chat_members` висели сразу 5 хендлеров (blocks, message_deletion,
welcome, captcha, group_statistics), но aiogram вызывает только первый подходящий —
поэтому капча и приветствие не срабатывали. Здесь всё выполняется по порядку:

вступление: блок ботов → режим одобрения → капча → приветствие → статистика → удаление служебного сообщения
выход:      прощание → отметка о выходе → статистика → удаление служебного сообщения
закреп:     удаление служебного сообщения

issue #12: капча, приветствие и прощание пишутся на языке чата (`lang`).
issue #50: при включённом режиме одобрения новички помечаются как ждущие одобрения.
issue #47: вышедший участник отмечается в ChatUser.left_at и не попадает в /inactive и /tagall;
статистика считается по часовому поясу чата.
"""
from __future__ import annotations

import logging
from typing import Awaitable

from aiogram import F, Router
from aiogram.types import Message

from bot.database import SessionFactory
from bot.handlers.chat.group_statistics import bump_stat
from bot.handlers.moderation.approve_mode import mark_new_members_pending
from bot.handlers.moderation.blocks import kick_blocked_bots
from bot.handlers.moderation.message_deletion import delete_service_message
from bot.handlers.welcome.captcha import start_captcha
from bot.handlers.welcome.goodbye import farewell
from bot.handlers.welcome.welcome import greet_members
from bot.services.user_service import mark_left

router = Router(name="service_events")
logger = logging.getLogger(__name__)


async def _safe(step: Awaitable[object], name: str) -> object | None:
    """Ошибка одного шага (нет прав, Telegram API) не должна отменять следующие."""
    try:
        return await step
    except Exception:
        logger.exception("Service event step %s failed", name)
        return None


async def forget_member(chat_id: int, user_id: int) -> None:
    async with SessionFactory() as session:
        await mark_left(session, chat_id, user_id)
        await session.commit()


@router.message(F.new_chat_members)
async def on_members_joined(message: Message, chat_settings: dict | None = None, lang: str = "ru") -> None:
    settings = chat_settings or {}
    bot, chat_id = message.bot, message.chat.id

    remaining = await _safe(kick_blocked_bots(bot, chat_id, settings, message.new_chat_members), "blocks")
    if remaining is None:
        remaining = message.new_chat_members
    humans = [m for m in remaining if not m.is_bot]

    await _safe(mark_new_members_pending(chat_id, settings, humans), "approve_mode")

    in_captcha = await _safe(start_captcha(bot, chat_id, settings, humans, lang=lang), "captcha") or []
    # Участников на капче поприветствуем после её прохождения (см. captcha.py).
    to_greet = [m for m in humans if m.id not in set(in_captcha)]
    await _safe(greet_members(bot, chat_id, settings, to_greet, lang=lang), "welcome")

    await _safe(bump_stat(chat_id, "joins_count", utc_offset=settings.get("utc_offset", 0)), "stats")
    await _safe(delete_service_message(message, settings), "cleanup")


@router.message(F.left_chat_member)
async def on_member_left(message: Message, chat_settings: dict | None = None, lang: str = "ru") -> None:
    settings = chat_settings or {}
    chat_id, member = message.chat.id, message.left_chat_member
    await _safe(farewell(message.bot, chat_id, settings, member, lang=lang), "goodbye")
    await _safe(forget_member(chat_id, member.id), "left")
    await _safe(bump_stat(chat_id, "leaves_count", utc_offset=settings.get("utc_offset", 0)), "stats")
    await _safe(delete_service_message(message, settings), "cleanup")


@router.message(F.pinned_message)
async def on_message_pinned(message: Message, chat_settings: dict | None = None) -> None:
    await _safe(delete_service_message(message, chat_settings or {}), "cleanup")
