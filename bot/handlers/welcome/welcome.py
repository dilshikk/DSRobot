"""Welcome: приветствие новых участников, с очисткой предыдущего приветствия."""
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.cache import redis
from bot.services.settings_service import update_settings

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


@router.message(F.new_chat_members)
async def greet_new_members(message: Message, chat_settings: dict) -> None:
    cfg = chat_settings.get("welcome", {})
    if not cfg.get("enabled", True):
        return

    if cfg.get("clean_old"):
        old_id = await redis.get(f"lastwelcome:{message.chat.id}")
        if old_id:
            try:
                await message.bot.delete_message(message.chat.id, int(old_id))
            except Exception:
                pass

    for member in message.new_chat_members:
        text = cfg.get("text", "Добро пожаловать, {mention}!").format(mention=member.mention_html())
        sent = await message.answer(text, parse_mode="HTML")
        if cfg.get("clean_old"):
            await redis.set(f"lastwelcome:{message.chat.id}", sent.message_id, ex=86400)
