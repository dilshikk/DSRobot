"""Discussion group settings: привязка обсуждения к каналу."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import get_or_create_chat

router = Router(name="discussion_group")


@router.message(Command("linkdiscussion"), HasRole("owner"))
async def link_discussion(message: Message, command: CommandObject) -> None:
    """Использование (в канале, куда добавлен бот): /linkdiscussion <group_id>"""
    if not command.args or not command.args.lstrip("-").isdigit():
        await message.answer("Использование: /linkdiscussion <id группы обсуждений>")
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "", message.chat.type)
        chat.discussion_group_id = int(command.args)
        await session.commit()
    await message.answer("\u2705 Группа обсуждений привязана. Комментарии под постами будут модерироваться ботом.")
