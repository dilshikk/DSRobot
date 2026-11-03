"""Link settings: удаление/санкция за ссылки, whitelist доменов, allow_admins.
Проверка вызывается из moderation_pipeline. Ответы — на языке чата (issue #12)."""
import re
from urllib.parse import urlsplit

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.chat_lang import get_chat_lang
from bot.services.moderation_actions import DEFAULT_MUTE_MINUTES, apply_sanction, parse_auto_action
from bot.services.settings_service import update_settings
from bot.utils.i18n import t
from bot.utils.permissions import is_privileged
from bot.utils.telegram import delete_message_safely, entity_text, message_entities, message_text

router = Router(name="link_settings")

URL_RE = re.compile(r"(https?://|t\.me/|www\.)[^\s]+", re.IGNORECASE)
LINK_ACTIONS = ("delete", "warn", "mute", "ban", "off")


def link_host(link: str) -> str:
    """Хост ссылки без www. и порта: "HTTPS://www.Google.com:443/x" -> "google.com"."""
    link = link.strip()
    if "://" not in link:
        link = "http://" + link
    try:
        host = urlsplit(link).hostname or ""
    except ValueError:
        return ""
    host = host.rstrip(".")
    return host[4:] if host.startswith("www.") else host


def is_whitelisted(host: str, whitelist: list[str]) -> bool:
    """Сам домен или его поддомен. Подстрока не подходит: google.com.evil.ru — не google.com (issue #41)."""
    return any(host == d or host.endswith("." + d) for d in (link_host(w) for w in whitelist) if d)


def extract_links(message: Message) -> list[str]:
    """Все ссылки сообщения: entities url/text_link (так Telegram помечает и голые домены) + regex."""
    links = []
    for entity in message_entities(message):
        if entity.type == "url":
            links.append(entity_text(message, entity))
        elif entity.type == "text_link" and entity.url:
            links.append(entity.url)
    links += [m.group(0) for m in URL_RE.finditer(message_text(message))]
    return links


@router.message(Command("linkaction"), HasRole("admin"))
async def set_link_action(message: Message, command: CommandObject, lang: str = "ru") -> None:
    values = parse_auto_action(command.args, LINK_ACTIONS)
    if values is None:
        await message.answer(t(lang, "link_action_usage"))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "link_settings", values)
    await message.answer(t(lang, "link_action_set", action=values["action"]))


@router.message(Command("allowlink"), HasRole("admin"))
async def whitelist_domain(message: Message, command: CommandObject, chat_settings: dict,
                           lang: str = "ru") -> None:
    if not command.args:
        await message.answer(t(lang, "allowlink_usage"))
        return
    domain = link_host(command.args.split()[0].lower())
    if not domain:
        await message.answer(t(lang, "allowlink_usage"))
        return
    whitelist = set(chat_settings.get("link_settings", {}).get("whitelist", []))
    whitelist.add(domain)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "link_settings", {"whitelist": list(whitelist)})
    await message.answer(t(lang, "allowlink_added", domain=domain))


@router.message(Command("denylink"), HasRole("admin"))
async def remove_whitelisted_domain(message: Message, command: CommandObject, chat_settings: dict,
                                    lang: str = "ru") -> None:
    domain = link_host(command.args.split()[0].lower()) if command.args else ""
    if not domain:
        await message.answer(t(lang, "denylink_usage"))
        return
    whitelist = chat_settings.get("link_settings", {}).get("whitelist", [])
    remaining = [w for w in whitelist if link_host(w) != domain]
    if len(remaining) == len(whitelist):
        await message.answer(t(lang, "denylink_missing", domain=domain))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "link_settings", {"whitelist": remaining})
    await message.answer(t(lang, "denylink_removed", domain=domain))


@router.message(Command("linkadmins"), HasRole("admin"))
async def set_allow_admins(message: Message, command: CommandObject, lang: str = "ru") -> None:
    arg = (command.args or "").strip().lower()
    if arg not in ("on", "off"):
        await message.answer(t(lang, "linkadmins_usage"))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "link_settings", {"allow_admins": arg == "on"})
    await message.answer(t(lang, "linkadmins_on" if arg == "on" else "linkadmins_off"))


async def check_links(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    cfg = chat_settings.get("link_settings", {})
    action = cfg.get("action", "delete")
    if action == "off":
        return False
    if is_privileged(chat_user_role) and cfg.get("allow_admins", True):
        return False
    whitelist = cfg.get("whitelist", [])
    # Каждая ссылка должна быть разрешена: раньше проверялась только первая (issue #41).
    if all(is_whitelisted(link_host(link), whitelist) for link in extract_links(message)):
        return False

    await delete_message_safely(message)
    if action != "delete":
        lang = await get_chat_lang(message.chat.id)
        duration = int(cfg.get("mute_minutes", DEFAULT_MUTE_MINUTES)) if action == "mute" else None
        await apply_sanction(message.bot, message.chat.id, message.from_user.id, action,
                             t(lang, "link_reason"), 0, duration, lang=lang)
    return True
