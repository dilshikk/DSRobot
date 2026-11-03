"""Topics settings: настройки форум-топиков супергруппы (создание/закрытие/ограничение фич по топику)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject

from bot.database import SessionFactory
from bot.database.models import TopicSettings
from bot.filters.roles import HasRole
from sqlalchemy import select

router = Router(name="topics_settings")


@router.message(Command("newtopic"), HasRole("admin"))
async def create_topic(message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Использование: /newtopic <название>")
        return
    topic = await message.bot.create_forum_topic(message.chat.id, name=command.args)
    async with SessionFactory() as session:
        session.add(TopicSettings(chat_id=message.chat.id, topic_id=topic.message_thread_id, name=command.args))
        await session.commit()
    await message.answer(f"\u2705 Топик «{command.args}» создан.")


@router.message(Command("closetopic"), HasRole("admin"))
async def close_topic(message) -> None:
    if not message.message_thread_id:
        await message.answer("Эта команда должна быть вызвана внутри топика.")
        return
    await message.bot.close_forum_topic(message.chat.id, message.message_thread_id)
    await message.answer("\U0001f512 Топик закрыт.")
