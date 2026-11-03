"""
Support for anonymous admins.
Основная логика (распознавание sender_chat.id == chat.id как admin) реализована в
ChatContextMiddleware — см. bot/middlewares/chat_context.py. Здесь — служебная команда,
позволяющая анонимному админу подтвердить личность боту (для команд, требующих reply).
Ответы — на языке чата (issue #12).
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.utils.i18n import t

router = Router(name="anonymous_admins")


@router.message(Command("whoami"))
async def whoami(message: Message, chat_user_role: str = "member", is_anonymous_admin: bool = False,
                 lang: str = "ru") -> None:
    if is_anonymous_admin:
        await message.answer(t(lang, "whoami_anonymous"))
    else:
        await message.answer(t(lang, "whoami_role", role=chat_user_role))
