"""Personal commands: пользовательские текстовые заметки/триггеры (#note -> ответ)."""
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select, delete

from bot.database import SessionFactory
from bot.database.models import PersonalCommand
from bot.filters.roles import HasRole

router = Router(name="personal_commands")


async def save_trigger(session, chat_id: int, trigger: str, response_type: str, content: str, author: int) -> bool:
    """Вставка или замена по (chat_id, trigger): повторный /addnote или /addmagic раньше падал
    на uq_chat_trigger (issue #45). Возвращает True, если триггер уже был и его заменили."""
    row = (await session.execute(select(PersonalCommand).where(
        PersonalCommand.chat_id == chat_id, PersonalCommand.trigger == trigger
    ))).scalar_one_or_none()
    if row is None:
        session.add(PersonalCommand(chat_id=chat_id, trigger=trigger, response_type=response_type,
                                    response_content=content, created_by=author))
    else:
        row.response_type, row.response_content, row.created_by = response_type, content, author
    await session.commit()
    return row is not None


@router.message(Command("addnote"), HasRole("admin"))
async def add_note(message: Message, command: CommandObject) -> None:
    if not command.args or " " not in command.args:
        await message.answer("Использование: /addnote <#триггер> <текст ответа>")
        return
    trigger, text = command.args.split(maxsplit=1)
    async with SessionFactory() as session:
        replaced = await save_trigger(session, message.chat.id, trigger.lower(), "text", text, message.from_user.id)
    await message.answer(f"\u2705 Заметка «{trigger}» {'обновлена' if replaced else 'сохранена'}.")


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


@router.message(Command("notes"))
async def list_notes(message: Message) -> None:
    async with SessionFactory() as session:
        triggers = (await session.execute(
            select(PersonalCommand.trigger).where(PersonalCommand.chat_id == message.chat.id).order_by(PersonalCommand.trigger)
        )).scalars().all()
    await message.answer("Заметки: " + ", ".join(triggers) if triggers else "Заметок пока нет.", parse_mode=None)


@router.message(F.text.startswith("#"))
async def trigger_note(message: Message) -> None:
    trigger = message.text.split()[0].lower()
    async with SessionFactory() as session:
        note = (await session.execute(select(PersonalCommand).where(
            PersonalCommand.chat_id == message.chat.id, PersonalCommand.trigger == trigger
        ))).scalar_one_or_none()
    if note and note.response_type == "text":
        await message.answer(note.response_content)
