"""
Personal commands: заметки чата (#триггер -> ответ).

issue #51:
- триггеры берутся из кэша Redis (services/triggers.py), а не SELECT на каждое «#»-сообщение;
- заметка может быть не только текстом: /addnote #триггер в ответ на фото, стикер, GIF,
  видео, файл или текстовое сообщение;
- /notes показывает заметки и magic-ответы раздельно;
- роутер работает только в группах, а сообщение без подходящей заметки не «съедается»
  хендлером и проходит к следующим роутерам.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import delete, select

from bot.database import SessionFactory
from bot.database.models import PersonalCommand
from bot.filters.roles import HasRole
from bot.services.triggers import (
    MAX_TRIGGER_LENGTH, NOTE_PREFIX, Trigger, extract_response, find_note, get_triggers,
    invalidate_triggers, send_response,
)

router = Router(name="personal_commands")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

ADD_NOTE_USAGE = (
    "Использование: /addnote #триггер текст ответа\n"
    "Или ответьте командой /addnote #триггер на сообщение: текст, фото, стикер, GIF, видео или файл."
)
DEL_NOTE_USAGE = "Использование: /delnote #триггер"


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


def note_trigger(raw: str | None) -> str | None:
    """'Rules' -> '#rules'. Пустой или слишком длинный триггер -> None."""
    trigger = (raw or "").strip().lower()
    if trigger and not trigger.startswith(NOTE_PREFIX):
        trigger = NOTE_PREFIX + trigger
    return trigger if 1 < len(trigger) <= MAX_TRIGGER_LENGTH else None


def parse_note(args: str | None, reply: Message | None) -> tuple[str, str, str] | None:
    """(триггер, тип, содержимое): текст из аргументов или содержимое сообщения, на которое ответили."""
    parts = (args or "").split(maxsplit=1)
    trigger = note_trigger(parts[0]) if parts else None
    if trigger is None:
        return None
    if len(parts) == 2:
        return trigger, "text", parts[1]
    response = extract_response(reply) if reply else None
    return (trigger, *response) if response else None


def notes_list_text(triggers: list[Trigger]) -> str:
    notes = sorted(t.trigger for t in triggers if t.is_note)
    magic = sorted(t.trigger for t in triggers if t.is_magic)
    if not notes and not magic:
        return "Заметок пока нет."
    lines = []
    if notes:
        lines.append("\U0001f4dd Заметки: " + ", ".join(notes))
    if magic:
        lines.append("\u2728 Magic-ответы: " + ", ".join(magic))
    return "\n".join(lines)


@router.message(Command("addnote"), HasRole("admin"))
async def add_note(message: Message, command: CommandObject) -> None:
    parsed = parse_note(command.args, message.reply_to_message)
    if parsed is None:
        await message.answer(ADD_NOTE_USAGE, parse_mode=None)
        return
    trigger, response_type, content = parsed
    author = message.from_user.id if message.from_user else 0
    async with SessionFactory() as session:
        replaced = await save_trigger(session, message.chat.id, trigger, response_type, content, author)
    await invalidate_triggers(message.chat.id)
    await message.answer(f"\u2705 Заметка «{trigger}» {'обновлена' if replaced else 'сохранена'}.", parse_mode=None)


@router.message(Command("delnote"), HasRole("admin"))
async def del_note(message: Message, command: CommandObject) -> None:
    trigger = note_trigger(command.args)
    if trigger is None:
        await message.answer(DEL_NOTE_USAGE, parse_mode=None)
        return
    async with SessionFactory() as session:
        result = await session.execute(delete(PersonalCommand).where(
            PersonalCommand.chat_id == message.chat.id, PersonalCommand.trigger == trigger
        ))
        await session.commit()
    await invalidate_triggers(message.chat.id)
    text = "\u2705 Заметка удалена." if result.rowcount else f"Заметки «{trigger}» нет."
    await message.answer(text, parse_mode=None)


@router.message(Command("notes"))
async def list_notes(message: Message) -> None:
    await message.answer(notes_list_text(await get_triggers(message.chat.id)), parse_mode=None)


async def note_match(message: Message) -> dict[str, Trigger] | bool:
    """Фильтр: подходящая заметка попадает в хендлер аргументом `note`."""
    text = message.text
    if not text or not text.startswith(NOTE_PREFIX):
        return False
    found = find_note(text, await get_triggers(message.chat.id))
    return {"note": found} if found else False


@router.message(note_match)
async def trigger_note(message: Message, note: Trigger) -> None:
    await send_response(message, note)
