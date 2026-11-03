"""Roles and permissions hierarchy: promote/demote внутри Telegram admin API."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import ChatPermissions, Message

from bot.filters.roles import HasRole

router = Router(name="roles_permissions")


@router.message(Command("promote"), HasRole("owner"))
async def promote(message: Message) -> None:
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя, которого нужно повысить.")
        return
    target = message.reply_to_message.from_user
    await message.bot.promote_chat_member(
        message.chat.id, target.id,
        can_delete_messages=True, can_restrict_members=True, can_invite_users=True,
        can_pin_messages=True, can_manage_chat=True,
    )
    await message.answer(f"\u2b06\ufe0f {target.mention_html()} назначен(а) администратором.", parse_mode="HTML")


@router.message(Command("demote"), HasRole("owner"))
async def demote(message: Message) -> None:
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение администратора, которого нужно понизить.")
        return
    target = message.reply_to_message.from_user
    await message.bot.promote_chat_member(
        message.chat.id, target.id,
        can_delete_messages=False, can_restrict_members=False, can_invite_users=False,
        can_pin_messages=False, can_manage_chat=False,
    )
    await message.answer(f"\u2b07\ufe0f {target.mention_html()} больше не администратор.", parse_mode="HTML")
