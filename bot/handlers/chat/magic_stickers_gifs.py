"""Magic Stickers/GIFs: авто-ответ стикером/гифкой на ключевое слово (та же таблица, что personal_commands).
Ответы — на языке чата (issue #12)."""
from html import escape

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import PersonalCommand
from bot.filters.roles import HasRole
from bot.utils.i18n import t

router = Router(name="magic_stickers_gifs")


@router.message(Command("addmagic"), HasRole("admin"))
async def add_magic(message: Message, command: CommandObject, lang: str = "ru") -> None:
    """Ответьте стикером/гифкой на команду: /addmagic КЛЮЧЕВОЕ_СЛОВО"""
    if not message.reply_to_message or not command.args or not message.from_user:
        await message.answer(t(lang, "addmagic_usage"))
        return
    reply = message.reply_to_message
    if reply.sticker:
        rtype, content = "sticker", reply.sticker.file_id
    elif reply.animation:
        rtype, content = "gif", reply.animation.file_id
    else:
        await message.answer(t(lang, "addmagic_wrong_media"))
        return

    async with SessionFactory() as session:
        session.add(PersonalCommand(chat_id=message.chat.id, trigger=command.args.lower(),
                                     response_type=rtype, response_content=content, created_by=message.from_user.id))
        await session.commit()
    # Ключевое слово пишет пользователь — экранируем, иначе «a<b» ломает HTML-разметку.
    await message.answer(t(lang, "addmagic_done", trigger=escape(command.args)))


@router.message(F.text, ~F.text.startswith("/"))
async def trigger_magic(message: Message) -> None:
    text_lower = (message.text or "").lower()
    async with SessionFactory() as session:
        notes = (await session.execute(select(PersonalCommand).where(
            PersonalCommand.chat_id == message.chat.id, PersonalCommand.response_type.in_(["sticker", "gif"])
        ))).scalars().all()
    for note in notes:
        if note.trigger in text_lower:
            if note.response_type == "sticker":
                await message.answer_sticker(note.response_content)
            else:
                await message.answer_animation(note.response_content)
            return
