"""
Support for anonymous admins.
Основная логика (распознавание sender_chat.id == chat.id как admin) реализована в
ChatContextMiddleware — см. bot/middlewares/chat_context.py. Здесь — служебная команда,
позволяющая анонимному админу подтвердить личность боту (для команд, требующих reply).
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="anonymous_admins")


@router.message(Command("whoami"))
async def whoami(message: Message, chat_user_role: str = "member", is_anonymous_admin: bool = False) -> None:
    if is_anonymous_admin:
        await message.answer("\U0001f47b Вы пишете как анонимный администратор \u2014 распознано.")
    else:
        await message.answer(f"Ваша роль в этом чате: {chat_user_role}")
