"""Topics settings: настройки форум-топиков супергруппы (создание/закрытие).
Ответы — на языке чата (issue #12)."""
from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject

from bot.database import SessionFactory
from bot.database.models import TopicSettings
from bot.filters.roles import HasRole
from bot.utils.i18n import t

router = Router(name="topics_settings")


@router.message(Command("newtopic"), HasRole("admin"))
async def create_topic(message, command: CommandObject, lang: str = "ru") -> None:
    if not command.args:
        await message.answer(t(lang, "newtopic_usage"))
        return
    topic = await message.bot.create_forum_topic(message.chat.id, name=command.args)
    async with SessionFactory() as session:
        session.add(TopicSettings(chat_id=message.chat.id, topic_id=topic.message_thread_id, name=command.args))
        await session.commit()
    await message.answer(t(lang, "newtopic_done", name=escape(command.args)))


@router.message(Command("closetopic"), HasRole("admin"))
async def close_topic(message, lang: str = "ru") -> None:
    if not message.message_thread_id:
        await message.answer(t(lang, "closetopic_outside"))
        return
    await message.bot.close_forum_topic(message.chat.id, message.message_thread_id)
    await message.answer(t(lang, "closetopic_done"))
