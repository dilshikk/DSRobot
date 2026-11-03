"""Warns settings: /warn /unwarn + настройка порога и действия при достижении max_warns.
Ответы — на языке чата (issue #12)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import ChatUser
from bot.filters.roles import HasRole
from bot.services.moderation_targets import prepare_target, run_sanction
from bot.services.settings_service import update_settings
from bot.utils.i18n import t

router = Router(name="warns")

LIMIT_ACTIONS = ("ban", "kick", "mute")


async def _get_warns(chat_id: int, user_id: int) -> int:
    async with SessionFactory() as session:
        cu = (await session.execute(
            select(ChatUser).where(ChatUser.chat_id == chat_id, ChatUser.user_id == user_id)
        )).scalar_one_or_none()
    return (cu.warns or 0) if cu else 0


@router.message(Command("warn"), HasRole("admin"))
async def cmd_warn(message: Message, command: CommandObject, chat_settings: dict, lang: str = "ru") -> None:
    prepared = await prepare_target(message, command.args, t(lang, "usage_warn"), lang=lang)
    if prepared is None:
        return
    target, reason = prepared
    if not await run_sanction(message, target, "warn", reason, lang=lang):
        return

    warns_count = await _get_warns(message.chat.id, target.user_id)
    cfg = chat_settings.get("warns", {})
    max_warns = cfg.get("max_warns", 3)
    await message.answer(t(lang, "user_warned", mention=target.mention, count=warns_count, max=max_warns),
                          parse_mode="HTML")

    if warns_count >= max_warns:
        action = cfg.get("action", "ban")
        if action not in LIMIT_ACTIONS:
            action = "ban"
        if await run_sanction(message, target, action, t(lang, "warn_limit_reason"), lang=lang):
            await message.answer(t(lang, "warn_limit_reached", action=action))


@router.message(Command("unwarn"), HasRole("admin"))
async def cmd_unwarn(message: Message, command: CommandObject, lang: str = "ru") -> None:
    prepared = await prepare_target(message, command.args, t(lang, "usage_unwarn"), protect=False, lang=lang)
    if prepared is None:
        return
    target, _ = prepared
    async with SessionFactory() as session:
        cu = (await session.execute(
            select(ChatUser).where(ChatUser.chat_id == message.chat.id, ChatUser.user_id == target.user_id)
        )).scalar_one_or_none()
        if cu is None or not cu.warns:
            await message.answer(t(lang, "no_warns"))
            return
        cu.warns -= 1
        await session.commit()
    await message.answer(t(lang, "warn_removed"))


@router.message(Command("setwarnlimit"), HasRole("admin"))
async def set_warn_limit(message: Message, command: CommandObject, lang: str = "ru") -> None:
    if not command.args or not command.args.isdigit() or int(command.args) < 1:
        await message.answer(t(lang, "warn_limit_usage"))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "warns", {"max_warns": int(command.args)})
    await message.answer(t(lang, "warn_limit_set", limit=command.args))
