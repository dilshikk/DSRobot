"""Personal commands: пользовательские текстовые заметки/триггеры (#note -> ответ)."""
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select, delete

from bot.database import SessionFactory
from bot.database.models import PersonalCommand
from bot.filters.roles import HasRole

router = Router(name="personal_commands")


@router.message(Command("addnote"), HasRole("admin"))
async def add_note(message: Message, command: CommandObject) -> None:
    if not command.args or " " not in command.args:
        await message.answer("Использование: /addnote <#триггер> <текст ответа>")
        return
    trigger, text = command.args.split(maxsplit=1)
    async with SessionFactory() as session:
        session.add(PersonalCommand(chat_id=message.chat.id, trigger=trigger.lower(),
                                     response_type="text", response_content=text, created_by=message.from_user.id))
        await session.commit()
    await message.answer(f"\u2705 Заметка «{trigger}» сохранена.")


@router.message(Command("delnote"), HasRole("admin"))
async def del_note(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Использование: /delnote <#триггер>")
        return
    async with SessionFactory() as session:
        await session.execute(delete(PersonalCommand).where(
            PersonalCommand.chat_id == message.chat.id, PersonalCommand.trigger == command.args.lower()
        ))
        await session.commit()
    await message.answer("\u2705 Заметка удалена.")


@router.message(F.text.startswith("#"))
async def trigger_note(message: Message) -> None:
    trigger = message.text.split()[0].lower()
    async with SessionFactory() as session:
        note = (await session.execute(select(PersonalCommand).where(
            PersonalCommand.chat_id == message.chat.id, PersonalCommand.trigger == trigger
        ))).scalar_one_or_none()
    if note and note.response_type == "text":
        await message.answer(note.response_content)
