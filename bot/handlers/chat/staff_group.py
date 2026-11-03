"""Staff group: отдельная группа модераторов, куда можно пересылать репорты (/report)."""
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import get_or_create_chat
from bot.utils.parsing import parse_chat_id

router = Router(name="staff_group")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))  # в личке нет chat_settings (issue #45)


@router.message(Command("setstaffgroup"), HasRole("owner"))
async def set_staff_group(message: Message, command: CommandObject) -> None:
    target_id = parse_chat_id(command.args)
    if target_id is None:
        await message.answer("Использование: /setstaffgroup <id группы стаффа>")
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        chat.staff_group_id = target_id
        await session.commit()
    await message.answer("\u2705 Группа стаффа подключена.")


@router.message(Command("report"))
async def report(message: Message) -> None:
    if not message.reply_to_message:
        await message.answer("Ответьте на нарушающее сообщение командой /report.")
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        staff_id = chat.staff_group_id
    if not staff_id:
        await message.answer("Группа стаффа не настроена (/setstaffgroup).")
        return
    await message.reply_to_message.forward(staff_id)
    # От анонимного админа from_user = GroupAnonymousBot, поэтому показываем sender_chat.
    reporter = escape(message.sender_chat.title or "") if message.sender_chat else message.from_user.mention_html()
    await message.bot.send_message(staff_id, f"\U0001f6a9 Репорт от {reporter} "
                                              f"в чате {escape(message.chat.title or '')}", parse_mode="HTML")
    await message.answer("\u2705 Репорт отправлен модераторам.")
