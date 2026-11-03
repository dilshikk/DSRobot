"""Link settings: удаление/санкция за ссылки, whitelist доменов, allow_admins.
Проверка вызывается из moderation_pipeline. Ответы — на языке чата (issue #12)."""
import re

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.chat_lang import get_chat_lang
from bot.services.moderation_actions import apply_sanction
from bot.services.settings_service import update_settings
from bot.utils.i18n import t
from bot.utils.permissions import is_privileged
from bot.utils.telegram import delete_message_safely, message_text

router = Router(name="link_settings")

URL_RE = re.compile(r"(https?://|t\.me/|www\.)[^\s]+", re.IGNORECASE)
LINK_ACTIONS = ("delete", "warn", "mute", "ban", "off")


@router.message(Command("linkaction"), HasRole("admin"))
async def set_link_action(message: Message, command: CommandObject, lang: str = "ru") -> None:
    action = (command.args or "").strip().lower()
    if action not in LINK_ACTIONS:
        await message.answer(t(lang, "link_action_usage"))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "link_settings", {"action": action})
    await message.answer(t(lang, "link_action_set", action=action))


@router.message(Command("allowlink"), HasRole("admin"))
async def whitelist_domain(message: Message, command: CommandObject, chat_settings: dict,
                           lang: str = "ru") -> None:
    if not command.args:
        await message.answer(t(lang, "allowlink_usage"))
        return
    domain = command.args.strip().lower()
    whitelist = set(chat_settings.get("link_settings", {}).get("whitelist", []))
    whitelist.add(domain)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "link_settings", {"whitelist": list(whitelist)})
    await message.answer(t(lang, "allowlink_added", domain=domain))


async def check_links(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    cfg = chat_settings.get("link_settings", {})
    action = cfg.get("action", "delete")
    text = message_text(message)
    if not text or action == "off":
        return False
    if is_privileged(chat_user_role) and cfg.get("allow_admins", True):
        return False
    match = URL_RE.search(text)
    if not match:
        return False
    if any(domain in match.group(0).lower() for domain in cfg.get("whitelist", [])):
        return False

    await delete_message_safely(message)
    if action != "delete":
        lang = await get_chat_lang(message.chat.id)
        await apply_sanction(message.bot, message.chat.id, message.from_user.id, action,
                             t(lang, "link_reason"), 0)
    return True
