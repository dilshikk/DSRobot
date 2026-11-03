"""
Magic Stickers/GIFs: авто-ответ стикером/GIF на ключевое слово (таблица personal_commands).

issue #51:
- совпадение только целым словом (utils/text_match.find_word): «hi» больше не срабатывает
  на «this» и «white»;
- триггеры берутся из кэша Redis (services/triggers.py), а не SELECT на каждое сообщение;
- роутер работает только в группах, а сообщение без триггера не «съедается» хендлером
  и проходит к следующим роутерам;
- /delmagic удаляет magic-ответ.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import delete

from bot.database import SessionFactory
from bot.database.models import PersonalCommand
from bot.filters.roles import HasRole
from bot.handlers.chat.personal_commands import save_trigger
from bot.services.triggers import (
    MAGIC_TYPES, MAX_TRIGGER_LENGTH, NOTE_PREFIX, Trigger, extract_response, find_magic,
    get_triggers, invalidate_triggers, send_response,
)

router = Router(name="magic_stickers_gifs")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

ADD_MAGIC_USAGE = "Ответьте на стикер или GIF командой: /addmagic ключевое слово (без «#»)"
DEL_MAGIC_USAGE = "Использование: /delmagic ключевое слово"


def magic_keyword(raw: str | None) -> str | None:
    """'  Good   Morning ' -> 'good morning'. Слова с «#» — это заметки, они не подходят."""
    keyword = " ".join((raw or "").lower().split())
    if not keyword or keyword.startswith(NOTE_PREFIX) or len(keyword) > MAX_TRIGGER_LENGTH:
        return None
    return keyword


@router.message(Command("addmagic"), HasRole("admin"))
async def add_magic(message: Message, command: CommandObject) -> None:
    keyword = magic_keyword(command.args)
    reply = message.reply_to_message
    response = extract_response(reply) if reply else None
    if keyword is None or response is None or response[0] not in MAGIC_TYPES:
        await message.answer(ADD_MAGIC_USAGE, parse_mode=None)
        return
    response_type, content = response
    author = message.from_user.id if message.from_user else 0
    async with SessionFactory() as session:
        replaced = await save_trigger(session, message.chat.id, keyword, response_type, content, author)
    await invalidate_triggers(message.chat.id)
    await message.answer(f"\u2705 Магический ответ на «{keyword}» {'обновлён' if replaced else 'сохранён'}.",
                         parse_mode=None)


@router.message(Command("delmagic"), HasRole("admin"))
async def del_magic(message: Message, command: CommandObject) -> None:
    keyword = magic_keyword(command.args)
    if keyword is None:
        await message.answer(DEL_MAGIC_USAGE, parse_mode=None)
        return
    async with SessionFactory() as session:
        result = await session.execute(delete(PersonalCommand).where(
            PersonalCommand.chat_id == message.chat.id, PersonalCommand.trigger == keyword,
            PersonalCommand.response_type.in_(MAGIC_TYPES),
        ))
        await session.commit()
    await invalidate_triggers(message.chat.id)
    text = "\u2705 Магический ответ удалён." if result.rowcount else f"Магического ответа на «{keyword}» нет."
    await message.answer(text, parse_mode=None)


async def magic_match(message: Message) -> dict[str, Trigger] | bool:
    """Фильтр: найденный триггер попадает в хендлер аргументом `magic`."""
    text = message.text
    if not text or text.startswith("/"):
        return False
    found = find_magic(text, await get_triggers(message.chat.id))
    return {"magic": found} if found else False


@router.message(magic_match)
async def trigger_magic(message: Message, magic: Trigger) -> None:
    await send_response(message, magic)
