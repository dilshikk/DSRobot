"""Roles and permissions hierarchy: promote/demote внутри Telegram admin API.
Ответы — на языке чата (issue #12)."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.filters.roles import HasRole
from bot.utils.i18n import t

router = Router(name="roles_permissions")


@router.message(Command("promote"), HasRole("owner"))
async def promote(message: Message, lang: str = "ru") -> None:
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer(t(lang, "promote_usage"))
        return
    target = message.reply_to_message.from_user
    await message.bot.promote_chat_member(
        message.chat.id, target.id,
        can_delete_messages=True, can_restrict_members=True, can_invite_users=True,
        can_pin_messages=True, can_manage_chat=True,
    )
    await message.answer(t(lang, "promote_done", mention=target.mention_html()), parse_mode="HTML")


@router.message(Command("demote"), HasRole("owner"))
async def demote(message: Message, lang: str = "ru") -> None:
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer(t(lang, "demote_usage"))
        return
    target = message.reply_to_message.from_user
    await message.bot.promote_chat_member(
        message.chat.id, target.id,
        can_delete_messages=False, can_restrict_members=False, can_invite_users=False,
        can_pin_messages=False, can_manage_chat=False,
    )
    await message.answer(t(lang, "demote_done", mention=target.mention_html()), parse_mode="HTML")
