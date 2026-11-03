"""Goodbye: сообщение при выходе участника. Ответы — на языке чата (issue #12)."""
from __future__ import annotations

from html import escape

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, User

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings
from bot.utils.html_fallback import send_html_or_escaped
from bot.utils.i18n import t

router = Router(name="goodbye")


@router.message(Command("setgoodbye"), HasRole("admin"))
async def set_goodbye(message: Message, command: CommandObject, lang: str = "ru") -> None:
    if not command.args:
        await message.answer(t(lang, "goodbye_usage"))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "goodbye", {"text": command.args, "enabled": True})
    await message.answer(t(lang, "goodbye_updated"))


@router.message(Command("goodbyeoff"), HasRole("admin"))
async def goodbye_off(message: Message, lang: str = "ru") -> None:
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "goodbye", {"enabled": False})
    await message.answer(t(lang, "goodbye_disabled"))


def goodbye_text(cfg: dict, lang: str, mention: str, escape_custom: bool = False) -> str:
    """Свой текст админа, если задан, иначе стандартное прощание на языке чата."""
    custom = cfg.get("text")
    if custom:
        return (escape(custom) if escape_custom else custom).format(mention=mention)
    return t(lang, "goodbye_default", mention=mention)


async def farewell(bot: Bot, chat_id: int, chat_settings: dict, member: User | None, lang: str = "ru") -> None:
    """Вызывается из service_events при выходе участника."""
    cfg = chat_settings.get("goodbye", {})
    if member is None or not cfg.get("enabled"):
        return
    mention = member.mention_html()
    await send_html_or_escaped(bot, chat_id, lambda esc: goodbye_text(cfg, lang, mention, esc))
