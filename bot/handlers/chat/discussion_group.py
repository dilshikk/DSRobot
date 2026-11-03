"""Discussion group settings: привязка обсуждения к каналу."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.chat_binding import verify_target
from bot.services.settings_service import get_or_create_chat
from bot.utils.parsing import parse_chat_id

router = Router(name="discussion_group")


@router.message(Command("linkdiscussion"), HasRole("owner"))
async def link_discussion(message: Message, command: CommandObject) -> None:
    """Использование (в канале, куда добавлен бот): /linkdiscussion <group_id>"""
    target_id = parse_chat_id(command.args)
    if target_id is None:
        await message.answer("Использование: /linkdiscussion <id группы обсуждений>")
        return
    # issue #46: вызывающий должен быть админом группы, а бот — её админом, чтобы модерировать.
    error = await verify_target(message.bot, message, target_id, bot_must_be_admin=True)
    if error:
        await message.answer(f"\u274c {error}")
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "", message.chat.type)
        chat.discussion_group_id = target_id
        await session.commit()
    await message.answer("\u2705 Группа обсуждений привязана. Комментарии под постами будут модерироваться ботом.")
