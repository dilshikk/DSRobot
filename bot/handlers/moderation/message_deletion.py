"""Message Deletion settings: очистка служебных сообщений (join/leave/pin) + автоудаление команд."""
import asyncio

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings

router = Router(name="message_deletion")


@router.message(Command("cleanservice"), HasRole("admin"))
async def toggle_clean_service(message: Message, chat_settings: dict) -> None:
    new_state = not chat_settings.get("message_deletion", {}).get("delete_service_messages", True)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "message_deletion", {"delete_service_messages": new_state})
    await message.answer(f"Удаление служебных сообщений: {'включено' if new_state else 'выключено'}")


@router.message(F.new_chat_members | F.left_chat_member | F.pinned_message)
async def delete_service_messages(message: Message, chat_settings: dict) -> None:
    if chat_settings.get("message_deletion", {}).get("delete_service_messages"):
        try:
            await message.delete()
        except Exception:
            pass


async def _delayed_delete(message: Message, delay: int) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


@router.message(F.text.startswith("/"))
async def maybe_autodelete_command(message: Message, chat_settings: dict) -> None:
    delay = chat_settings.get("message_deletion", {}).get("delete_commands_after_sec", 0)
    if delay:
        asyncio.create_task(_delayed_delete(message, delay))
