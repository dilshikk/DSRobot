"""Personal commands: пользовательские текстовые заметки/триггеры (#note -> ответ).
Ответы — на языке чата (issue #12)."""
from html import escape

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select, delete

from bot.database import SessionFactory
from bot.database.models import PersonalCommand
from bot.filters.roles import HasRole
from bot.utils.i18n import t

router = Router(name="personal_commands")


@router.message(Command("addnote"), HasRole("admin"))
async def add_note(message: Message, command: CommandObject, lang: str = "ru") -> None:
    if not command.args or " " not in command.args or not message.from_user:
        await message.answer(t(lang, "addnote_usage"))
        return
    trigger, text = command.args.split(maxsplit=1)
    async with SessionFactory() as session:
        session.add(PersonalCommand(chat_id=message.chat.id, trigger=trigger.lower(),
                                     response_type="text", response_content=text, created_by=message.from_user.id))
        await session.commit()
    await message.answer(t(lang, "addnote_done", trigger=escape(trigger)))


@router.message(Command("delnote"), HasRole("admin"))
async def del_note(message: Message, command: CommandObject, lang: str = "ru") -> None:
    if not command.args:
        await message.answer(t(lang, "delnote_usage"))
        return
    trigger = command.args.strip().lower()
    async with SessionFactory() as session:
        result = await session.execute(delete(PersonalCommand).where(
            PersonalCommand.chat_id == message.chat.id, PersonalCommand.trigger == trigger
        ))
        await session.commit()
    # Раньше бот всегда писал «удалена», даже если такой заметки не было.
    if not result.rowcount:
        await message.answer(t(lang, "note_not_found", trigger=escape(trigger)))
        return
    await message.answer(t(lang, "delnote_done"))


@router.message(F.text.startswith("#"))
async def trigger_note(message: Message) -> None:
    trigger = message.text.split()[0].lower()
    async with SessionFactory() as session:
        note = (await session.execute(select(PersonalCommand).where(
            PersonalCommand.chat_id == message.chat.id, PersonalCommand.trigger == trigger
        ))).scalar_one_or_none()
    if note and note.response_type == "text":
        await message.answer(note.response_content)
