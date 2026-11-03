"""Staff group: отдельная группа модераторов, куда можно пересылать репорты (/report)."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import get_or_create_chat

router = Router(name="staff_group")


@router.message(Command("setstaffgroup"), HasRole("owner"))
async def set_staff_group(message: Message, command: CommandObject) -> None:
    if not command.args or not command.args.lstrip("-").isdigit():
        await message.answer("Использование: /setstaffgroup <id группы стаффа>")
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        chat.staff_group_id = int(command.args)
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
    await message.bot.send_message(staff_id, f"\U0001f6a9 Репорт от {message.from_user.mention_html()} "
                                              f"в чате {message.chat.title}", parse_mode="HTML")
    await message.answer("\u2705 Репорт отправлен модераторам.")
