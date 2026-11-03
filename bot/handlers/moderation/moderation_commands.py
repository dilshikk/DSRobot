"""
Основные команды модерации: /ban /mute /kick /unban /unmute.
Цель — ответ на сообщение, @username или числовой id (см. services/moderation_targets.py).
Ответы — на языке чата (issue #12): `lang` прокидывает ChatContextMiddleware.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.filters.roles import HasRole
from bot.services.moderation_targets import prepare_target, run_sanction
from bot.utils.i18n import t

router = Router(name="moderation_commands")

DURATION_MAP = {"m": 1, "h": 60, "d": 1440, "w": 10080}


def _parse_duration(raw: str | None) -> int | None:
    if not raw or len(raw) < 2 or raw[-1] not in DURATION_MAP or not raw[:-1].isdigit():
        return None
    return int(raw[:-1]) * DURATION_MAP[raw[-1]]


@router.message(Command("ban"), HasRole("admin"))
async def cmd_ban(message: Message, command: CommandObject, lang: str = "ru") -> None:
    prepared = await prepare_target(message, command.args, t(lang, "usage_ban"), lang=lang)
    if prepared is None:
        return
    target, reason = prepared
    if await run_sanction(message, target, "ban", reason, lang=lang):
        await message.answer(t(lang, "user_banned", mention=target.mention), parse_mode="HTML")


@router.message(Command("unban"), HasRole("admin"))
async def cmd_unban(message: Message, command: CommandObject, lang: str = "ru") -> None:
    prepared = await prepare_target(message, command.args, t(lang, "usage_unban"), protect=False, lang=lang)
    if prepared is None:
        return
    target, _ = prepared
    if await run_sanction(message, target, "unban", lang=lang):
        await message.answer(t(lang, "user_unbanned"))


@router.message(Command("kick"), HasRole("admin"))
async def cmd_kick(message: Message, command: CommandObject, lang: str = "ru") -> None:
    prepared = await prepare_target(message, command.args, t(lang, "usage_kick"), lang=lang)
    if prepared is None:
        return
    target, reason = prepared
    if await run_sanction(message, target, "kick", reason, lang=lang):
        await message.answer(t(lang, "user_kicked"))


@router.message(Command("mute"), HasRole("admin"))
async def cmd_mute(message: Message, command: CommandObject, lang: str = "ru") -> None:
    prepared = await prepare_target(message, command.args, t(lang, "usage_mute"), lang=lang)
    if prepared is None:
        return
    target, reason = prepared
    duration = None
    if reason:
        first_word, *rest = reason.split(maxsplit=1)
        parsed = _parse_duration(first_word)
        if parsed:
            duration = parsed
            reason = rest[0] if rest else ""
    if await run_sanction(message, target, "mute", reason, duration, lang=lang):
        await message.answer(t(lang, "user_muted", mention=target.mention), parse_mode="HTML")


@router.message(Command("unmute"), HasRole("admin"))
async def cmd_unmute(message: Message, command: CommandObject, lang: str = "ru") -> None:
    prepared = await prepare_target(message, command.args, t(lang, "usage_unmute"), protect=False, lang=lang)
    if prepared is None:
        return
    target, _ = prepared
    if await run_sanction(message, target, "unmute", lang=lang):
        await message.answer(t(lang, "user_unmuted"))
