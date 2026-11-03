"""Staff group: отдельная группа модераторов, куда можно пересылать репорты (/report)."""
import logging
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.chat_binding import release_report, reserve_report, verify_target
from bot.services.settings_service import get_or_create_chat
from bot.utils.parsing import parse_chat_id
from bot.utils.permissions import is_privileged

router = Router(name="staff_group")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))  # в личке нет chat_settings (issue #45)
logger = logging.getLogger(__name__)


@router.message(Command("setstaffgroup"), HasRole("owner"))
async def set_staff_group(message: Message, command: CommandObject) -> None:
    target_id = parse_chat_id(command.args)
    if target_id is None:
        await message.answer("Использование: /setstaffgroup <id группы стаффа>")
        return
    # issue #46: нельзя направить репорты в чужой чат.
    error = await verify_target(message.bot, message, target_id)
    if error:
        await message.answer(f"\u274c {error}")
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        chat.staff_group_id = target_id
        await session.commit()
    await message.answer("\u2705 Группа стаффа подключена.")


def _reporter_id(message: Message) -> int:
    # От анонимного админа from_user = GroupAnonymousBot, поэтому считаем по sender_chat.
    if message.sender_chat:
        return message.sender_chat.id
    return message.from_user.id if message.from_user else 0


@router.message(Command("report"))
async def report(message: Message, chat_user_role: str = "member") -> None:
    target = message.reply_to_message
    if not target:
        await message.answer("Ответьте на нарушающее сообщение командой /report.")
        return
    async with SessionFactory() as session:
        chat = await get_or_create_chat(session, message.chat.id, message.chat.title or "")
        staff_id = chat.staff_group_id
    if not staff_id:
        await message.answer("Группа стаффа не настроена (/setstaffgroup).")
        return
    # issue #46: кулдаун по пользователю и чату, одно сообщение репортится один раз.
    refusal = await reserve_report(
        message.chat.id, _reporter_id(message), target.message_id, privileged=is_privileged(chat_user_role),
    )
    if refusal:
        await message.answer(refusal)
        return
    reporter = escape(message.sender_chat.title or "") if message.sender_chat else message.from_user.mention_html()
    try:
        await target.forward(staff_id)
        await message.bot.send_message(staff_id, f"\U0001f6a9 Репорт от {reporter} "
                                                  f"в чате {escape(message.chat.title or '')}", parse_mode="HTML")
    except TelegramAPIError as exc:
        logger.warning("Cannot deliver report from chat %s to %s: %s", message.chat.id, staff_id, exc)
        await release_report(message.chat.id, target.message_id)
        await message.answer("Не удалось отправить репорт: бот не может писать в группу стаффа.")
        return
    await message.answer("\u2705 Репорт отправлен модераторам.")
