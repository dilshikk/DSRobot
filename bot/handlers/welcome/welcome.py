"""Welcome: приветствие новых участников, с очисткой предыдущего приветствия.
Ответы — на языке чата (issue #12)."""
from __future__ import annotations

from html import escape

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, User

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.cache import redis
from bot.services.settings_service import update_settings
from bot.utils.html_fallback import send_html_or_escaped
from bot.utils.i18n import t
from bot.utils.telegram import delete_by_id_safely

router = Router(name="welcome")


@router.message(Command("setwelcome"), HasRole("admin"))
async def set_welcome(message: Message, command: CommandObject, lang: str = "ru") -> None:
    if not command.args:
        await message.answer(t(lang, "welcome_usage"))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "welcome", {"text": command.args, "enabled": True})
    await message.answer(t(lang, "welcome_updated"))


@router.message(Command("welcomeoff"), HasRole("admin"))
async def welcome_off(message: Message, lang: str = "ru") -> None:
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "welcome", {"enabled": False})
    await message.answer(t(lang, "welcome_disabled"))


def welcome_text(cfg: dict, lang: str, mention: str, escape_custom: bool = False) -> str:
    """Свой текст админа, если задан, иначе стандартное приветствие на языке чата."""
    custom = cfg.get("text")
    if custom:
        return (escape(custom) if escape_custom else custom).format(mention=mention)
    return t(lang, "welcome_default", mention=mention)


async def greet_members(
    bot: Bot, chat_id: int, chat_settings: dict, members: list[User], lang: str = "ru",
) -> None:
    """Вызывается из service_events (вступление) и из captcha (после прохождения проверки)."""
    cfg = chat_settings.get("welcome", {})
    if not members or not cfg.get("enabled", True):
        return

    if cfg.get("clean_old"):
        old_id = await redis.get(f"lastwelcome:{chat_id}")
        if old_id:
            await delete_by_id_safely(bot, chat_id, int(old_id))

    for member in members:
        mention = member.mention_html()
        sent = await send_html_or_escaped(bot, chat_id, lambda esc: welcome_text(cfg, lang, mention, esc))
        if cfg.get("clean_old"):
            await redis.set(f"lastwelcome:{chat_id}", sent.message_id, ex=86400)
