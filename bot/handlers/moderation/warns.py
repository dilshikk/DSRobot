"""Warns settings: /warn /unwarn + настройка порога и действия при достижении max_warns."""
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
async def cmd_warn(message: Message, command: CommandObject, chat_settings: dict) -> None:
    prepared = await prepare_target(message, command.args, "/warn [причина]")
    if prepared is None:
        return
    target, reason = prepared
    if not await run_sanction(message, target, "warn", reason):
        return

    warns_count = await _get_warns(message.chat.id, target.user_id)
    cfg = chat_settings.get("warns", {})
    max_warns = cfg.get("max_warns", 3)
    await message.answer(t("ru", "user_warned", mention=target.mention, count=warns_count, max=max_warns),
                          parse_mode="HTML")

    if warns_count >= max_warns:
        action = cfg.get("action", "ban")
        if action not in LIMIT_ACTIONS:
            action = "ban"
        if await run_sanction(message, target, action, "Достигнут лимит предупреждений"):
            await message.answer(f"\U0001f6ab Лимит предупреждений исчерпан \u2014 применено действие «{action}».")


@router.message(Command("unwarn"), HasRole("admin"))
async def cmd_unwarn(message: Message, command: CommandObject) -> None:
    prepared = await prepare_target(message, command.args, "/unwarn", protect=False)
    if prepared is None:
        return
    target, _ = prepared
    async with SessionFactory() as session:
        cu = (await session.execute(
            select(ChatUser).where(ChatUser.chat_id == message.chat.id, ChatUser.user_id == target.user_id)
        )).scalar_one_or_none()
        if cu is None or not cu.warns:
            await message.answer("У пользователя нет предупреждений.")
            return
        cu.warns -= 1
        await session.commit()
    await message.answer("\u2705 Одно предупреждение снято.")


@router.message(Command("setwarnlimit"), HasRole("admin"))
async def set_warn_limit(message: Message, command: CommandObject) -> None:
    if not command.args or not command.args.isdigit() or int(command.args) < 1:
        await message.answer("Использование: /setwarnlimit ЧИСЛО (не меньше 1)")
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "warns", {"max_warns": int(command.args)})
    await message.answer(f"\u2705 Лимит предупреждений установлен: {command.args}")
