"""
Апдейты chat_member: повышение, понижение, бан, выход участника (issue #11).

Сразу сбрасывают кэш роли и обновляют ChatUser.role, чтобы права разжалованного
админа пропадали мгновенно, а не через минуту. Telegram присылает chat_member только
если бот — администратор чата и тип апдейта запрошен в allowed_updates (см. main.py).
"""
from aiogram import Router
from aiogram.types import ChatMemberUpdated

from bot.services.roles import sync_member_role

router = Router(name="member_updates")


@router.chat_member()
async def on_chat_member_updated(event: ChatMemberUpdated) -> None:
    await sync_member_role(event.chat, event.new_chat_member)
