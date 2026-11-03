"""Основные команды модерации: /ban /mute /kick /warn /unwarn /unban /unmute — работают ответом на сообщение."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.filters.roles import HasRole
from bot.services.moderation_actions import apply_sanction
from bot.utils.i18n import t

router = Router(name="moderation_commands")

DURATION_MAP = {"m": 1, "h": 60, "d": 1440, "w": 10080}


def _parse_duration(raw: str | None) -> int | None:
    if not raw or len(raw) < 2 or raw[-1] not in DURATION_MAP or not raw[:-1].isdigit():
        return None
    return int(raw[:-1]) * DURATION_MAP[raw[-1]]


async def _target_and_reason(message: Message, command: CommandObject) -> tuple[int | None, str]:
    if message.reply_to_message:
        return message.reply_to_message.from_user.id, (command.args or "")
    return None, ""


@router.message(Command("ban"), HasRole("admin"))
async def cmd_ban(message: Message, command: CommandObject) -> None:
    target_id, reason = await _target_and_reason(message, command)
    if not target_id:
        await message.answer("Ответьте на сообщение пользователя: /ban [причина]")
        return
    await apply_sanction(message.bot, message.chat.id, target_id, "ban", reason, message.from_user.id)
    await message.answer(t("ru", "user_banned", mention=message.reply_to_message.from_user.mention_html()),
                          parse_mode="HTML")


@router.message(Command("unban"), HasRole("admin"))
async def cmd_unban(message: Message, command: CommandObject) -> None:
    target_id, _ = await _target_and_reason(message, command)
    if not target_id:
        await message.answer("Ответьте на сообщение пользователя: /unban")
        return
    await apply_sanction(message.bot, message.chat.id, target_id, "unban", "", message.from_user.id)
    await message.answer("\u2705 Разбанен(а).")


@router.message(Command("kick"), HasRole("admin"))
async def cmd_kick(message: Message, command: CommandObject) -> None:
    target_id, reason = await _target_and_reason(message, command)
    if not target_id:
        await message.answer("Ответьте на сообщение пользователя: /kick [причина]")
        return
    await apply_sanction(message.bot, message.chat.id, target_id, "kick", reason, message.from_user.id)
    await message.answer("\U0001f465 Пользователь удалён из чата (может зайти повторно).")


@router.message(Command("mute"), HasRole("admin"))
async def cmd_mute(message: Message, command: CommandObject) -> None:
    target_id, reason = await _target_and_reason(message, command)
    if not target_id:
        await message.answer("Ответьте на сообщение пользователя: /mute [1h/1d/...] [причина]")
        return
    duration = None
    if reason:
        first_word, *rest = reason.split(maxsplit=1)
        parsed = _parse_duration(first_word)
        if parsed:
            duration = parsed
            reason = rest[0] if rest else ""
    await apply_sanction(message.bot, message.chat.id, target_id, "mute", reason, message.from_user.id, duration)
    await message.answer(t("ru", "user_muted", mention=message.reply_to_message.from_user.mention_html()),
                          parse_mode="HTML")


@router.message(Command("unmute"), HasRole("admin"))
async def cmd_unmute(message: Message, command: CommandObject) -> None:
    target_id, _ = await _target_and_reason(message, command)
    if not target_id:
        await message.answer("Ответьте на сообщение пользователя: /unmute")
        return
    await apply_sanction(message.bot, message.chat.id, target_id, "unmute", "", message.from_user.id)
    await message.answer("\U0001f50a Размучен(а).")
