"""Staff group: отдельная группа модераторов, куда можно пересылать репорты (/report).
Ответы — на языке чата (issue #12)."""
from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import get_or_create_chat
from bot.utils.i18n import t

router = Router(name="staff_group")


def reporter_mention(message: Message) -> str:
    """У сообщения от имени канала нет from_user — раньше /report падал с AttributeError."""
    if message.from_user:
        return message.from_user.mention_html()
    sender = message.sender_chat
    return escape(sender.title or str(sender.id)) if sender else "?"


def report_notice_text(lang: str, reporter: str, chat_title: str | None) -> str:
    # Название чата задают люди — экранируем, иначе «A<B» ломает HTML-разметку уведомления.
    return t(lang, "report_staff_notice", reporter=reporter, chat=escape(chat_title or ""))


@router.message(Command("setstaffgroup"), HasRole("owner"))
async def set_staff_group(message: Message, command: CommandObject, lang: str = "ru") -> None:
    if not command.args or not command.args.lstrip("-").isdigit():
        await message.answer(t(lang, "setstaffgroup_usage"))
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        chat.staff_group_id = int(command.args)
        await session.commit()
    await message.answer(t(lang, "setstaffgroup_done"))


@router.message(Command("report"))
async def report(message: Message, lang: str = "ru") -> None:
    if not message.reply_to_message:
        await message.answer(t(lang, "report_usage"))
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        staff_id = chat.staff_group_id
    if not staff_id:
        await message.answer(t(lang, "report_no_staff"))
        return
    await message.reply_to_message.forward(staff_id)
    await message.bot.send_message(
        staff_id, report_notice_text(lang, reporter_mention(message), message.chat.title), parse_mode="HTML",
    )
    await message.answer(t(lang, "report_sent"))
