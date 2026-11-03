"""
Определение роли пользователя в чате (issue #11).

Источники роли по приоритету:
1. DEVELOPER_USER_IDS из конфига -> developer (во всех чатах);
2. статус в Telegram (get_chat_member) -> owner / admin;
3. внутренняя custom-роль бота (/setrole) -> custom + её права;
4. иначе member.

Результат кэшируется в Redis на ROLE_CACHE_TTL секунд. Кэш сбрасывается сразу при
апдейте chat_member (повышение/понижение в Telegram) и при /setrole, поэтому
разжалованный админ больше не сохраняет права ещё минуту.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Chat as TgChat
from aiogram.types import ChatMember, ChatMemberAdministrator, ChatMemberBanned, ChatMemberOwner
from sqlalchemy import select

from bot.config import settings
from bot.database import SessionFactory
from bot.database.models import ChatUser, CommandPermission, CustomRole
from bot.services.cache import get_json, redis, set_json
from bot.services.settings_service import get_or_create_chat
from bot.services.user_service import ensure_chat_user, upsert_tg_user

logger = logging.getLogger(__name__)

ROLE_CACHE_TTL = 60
COMMAND_PERMISSIONS_CACHE_TTL = 300


@dataclass(frozen=True)
class Access:
    role: str
    permissions: frozenset[str] = field(default_factory=frozenset)


def role_cache_key(chat_id: int, user_id: int) -> str:
    return f"role:{chat_id}:{user_id}"


def command_permissions_cache_key(chat_id: int) -> str:
    return f"cmdperm:{chat_id}"


async def invalidate_role(chat_id: int, user_id: int) -> None:
    await redis.delete(role_cache_key(chat_id, user_id))


async def invalidate_command_permissions(chat_id: int) -> None:
    await redis.delete(command_permissions_cache_key(chat_id))


def role_from_member(member: ChatMember) -> str:
    if isinstance(member, ChatMemberOwner):
        return "owner"
    if isinstance(member, ChatMemberAdministrator):
        return "admin"
    return "member"


def stored_role(member: ChatMember, custom_role_id: int | None) -> str:
    """Значение ChatUser.role для статуса Telegram. Custom-роль переживает понижение админа."""
    telegram_role = role_from_member(member)
    if telegram_role != "member":
        return telegram_role
    if isinstance(member, ChatMemberBanned):
        return "banned"
    return "custom" if custom_role_id is not None else "member"


def _from_cache(cached: object) -> Access | None:
    if isinstance(cached, dict):
        return Access(str(cached.get("role", "member")), frozenset(cached.get("permissions", [])))
    if isinstance(cached, str):  # старый формат кэша — просто строка с ролью
        return Access(cached)
    return None


async def _custom_access(chat_id: int, user_id: int) -> Access | None:
    async with SessionFactory() as session:
        row = (await session.execute(
            select(CustomRole.permissions)
            .join(ChatUser, ChatUser.custom_role_id == CustomRole.id)
            .where(ChatUser.chat_id == chat_id, ChatUser.user_id == user_id, ChatUser.role == "custom")
        )).first()
    if row is None:
        return None
    permissions = frozenset(name for name, enabled in (row.permissions or {}).items() if enabled)
    return Access("custom", permissions)


async def resolve_access(bot: Bot, chat_id: int, user_id: int) -> Access:
    if user_id in settings.developer_ids:
        return Access("developer")

    key = role_cache_key(chat_id, user_id)
    cached = _from_cache(await get_json(key))
    if cached is not None:
        return cached

    try:
        role = role_from_member(await bot.get_chat_member(chat_id, user_id))
    except TelegramAPIError as exc:
        # Безопасный вариант по умолчанию — обычный участник без прав Telegram.
        logger.warning("Cannot resolve role of %s in chat %s: %s", user_id, chat_id, exc)
        role = "member"

    access = Access(role)
    if role == "member":
        access = await _custom_access(chat_id, user_id) or access

    await set_json(key, {"role": access.role, "permissions": sorted(access.permissions)}, ex=ROLE_CACHE_TTL)
    return access


async def get_command_min_roles(chat_id: int) -> dict[str, str]:
    """Переопределения из редактора прав: {команда: минимальная роль}. С кэшем в Redis."""
    key = command_permissions_cache_key(chat_id)
    cached = await get_json(key)
    if isinstance(cached, dict):
        return cached
    async with SessionFactory() as session:
        rows = (await session.execute(
            select(CommandPermission.command, CommandPermission.min_role).where(CommandPermission.chat_id == chat_id)
        )).all()
    overrides = {row.command: row.min_role for row in rows}
    await set_json(key, overrides, ex=COMMAND_PERMISSIONS_CACHE_TTL)
    return overrides


async def sync_member_role(chat: TgChat, member: ChatMember) -> None:
    """Апдейт chat_member: сбрасывает кэш роли и синхронизирует ChatUser.role с Telegram."""
    user = member.user
    await invalidate_role(chat.id, user.id)
    if user.is_bot:
        return
    async with SessionFactory() as session:
        await get_or_create_chat(session, chat.id, chat.title or "", chat.type)
        await upsert_tg_user(session, user)
        chat_user = await ensure_chat_user(session, chat.id, user.id)
        chat_user.role = stored_role(member, chat_user.custom_role_id)
        await session.commit()
