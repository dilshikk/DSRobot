"""Discussion group settings: привязка обсуждения к каналу. Ответы — на языке чата (issue #12)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import get_or_create_chat
from bot.utils.i18n import t

router = Router(name="discussion_group")


@router.message(Command("linkdiscussion"), HasRole("owner"))
async def link_discussion(message: Message, command: CommandObject, lang: str = "ru") -> None:
    """Использование (в канале, куда добавлен бот): /linkdiscussion ID_ГРУППЫ"""
    if not command.args or not command.args.lstrip("-").isdigit():
        await message.answer(t(lang, "linkdiscussion_usage"))
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "", message.chat.type)
        chat.discussion_group_id = int(command.args)
        await session.commit()
    await message.answer(t(lang, "linkdiscussion_done"))
