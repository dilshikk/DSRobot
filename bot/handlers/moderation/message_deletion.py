"""Message Deletion settings: очистка служебных сообщений (join/leave/pin) + автоудаление команд.

Само удаление вызывается из service_events (служебные сообщения) и moderation_pipeline
(команды). Раньше это были хендлеры, которые перехватывали вступления и все команды
из роутеров ниже по списку (issue #1).
"""
import asyncio

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings
from bot.utils.telegram import delete_message_safely

router = Router(name="message_deletion")

# Держим ссылки на фоновые задачи, иначе сборщик мусора может удалить их до выполнения.
_pending_tasks: set[asyncio.Task] = set()


@router.message(Command("cleanservice"), HasRole("admin"))
async def toggle_clean_service(message: Message, chat_settings: dict) -> None:
    new_state = not chat_settings.get("message_deletion", {}).get("delete_service_messages", True)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "message_deletion", {"delete_service_messages": new_state})
    await message.answer(f"Удаление служебных сообщений: {'включено' if new_state else 'выключено'}")


async def delete_service_message(message: Message, chat_settings: dict) -> None:
    if chat_settings.get("message_deletion", {}).get("delete_service_messages"):
        await delete_message_safely(message)


async def _delayed_delete(message: Message, delay: int) -> None:
    await asyncio.sleep(delay)
    await delete_message_safely(message)


def schedule_command_autodelete(message: Message, chat_settings: dict) -> None:
    delay = chat_settings.get("message_deletion", {}).get("delete_commands_after_sec", 0)
    if delay:
        task = asyncio.create_task(_delayed_delete(message, delay))
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)
