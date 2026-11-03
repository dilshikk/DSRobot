"""Welcome: приветствие новых участников, с очисткой предыдущего приветствия."""
from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, User

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.cache import redis
from bot.services.settings_service import update_settings
from bot.utils.telegram import delete_by_id_safely

router = Router(name="welcome")


@router.message(Command("setwelcome"), HasRole("admin"))
async def set_welcome(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Использование: /setwelcome <текст с {mention}>")
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "welcome", {"text": command.args, "enabled": True})
    await message.answer("\u2705 Приветствие обновлено.")


@router.message(Command("welcomeoff"), HasRole("admin"))
async def welcome_off(message: Message) -> None:
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "welcome", {"enabled": False})
    await message.answer("Приветствие выключено.")


async def greet_members(bot: Bot, chat_id: int, chat_settings: dict, members: list[User]) -> None:
    """Вызывается из service_events (вступление) и из captcha (после прохождения проверки)."""
    cfg = chat_settings.get("welcome", {})
    if not members or not cfg.get("enabled", True):
        return

    if cfg.get("clean_old"):
        old_id = await redis.get(f"lastwelcome:{chat_id}")
        if old_id:
            await delete_by_id_safely(bot, chat_id, int(old_id))

    for member in members:
        text = cfg.get("text", "Добро пожаловать, {mention}!").format(mention=member.mention_html())
        sent = await bot.send_message(chat_id, text, parse_mode="HTML")
        if cfg.get("clean_old"):
            await redis.set(f"lastwelcome:{chat_id}", sent.message_id, ex=86400)
