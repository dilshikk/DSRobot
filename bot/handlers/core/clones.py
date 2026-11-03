"""
Bot clones support: владелец может зарегистрировать доп. токен, и оркестратор
(вне этого процесса, см. README «Клоны») поднимет ещё один инстанс бота на той же кодовой базе.
Здесь — только CRUD в таблице bot_clones.
"""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.database.models import BotClone

router = Router(name="clones")


@router.message(Command("addclone"))
async def add_clone(message: Message, command: CommandObject) -> None:
    if message.chat.type != "private" or not command.args:
        await message.answer("Использование (в личке боту): /addclone <token>")
        return
    async with SessionFactory() as session:
        session.add(BotClone(owner_user_id=message.from_user.id, token=command.args.strip()))
        await session.commit()
    await message.answer("\u2705 Токен клона сохранён. Оркестратор поднимет инстанс в течение минуты.")


@router.message(Command("myclones"))
async def list_clones(message: Message) -> None:
    async with SessionFactory() as session:
        from sqlalchemy import select
        rows = (await session.execute(
            select(BotClone).where(BotClone.owner_user_id == message.from_user.id)
        )).scalars().all()
    if not rows:
        await message.answer("У вас нет активных клонов.")
        return
    lines = [f"• @{c.bot_username or '???'} — {'активен' if c.is_active else 'выключен'}" for c in rows]
    await message.answer("\n".join(lines))
