"""Alphabets: ограничение сообщений только разрешёнными алфавитами (борьба с непонятным спамом/флудом).
Проверка вызывается из moderation_pipeline. Ответы — на языке чата (issue #12)."""
import re
import unicodedata

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings
from bot.utils.i18n import t
from bot.utils.permissions import is_privileged
from bot.utils.telegram import delete_message_safely

router = Router(name="alphabets")

SCRIPT_PATTERNS = {
    "cyrillic": re.compile(r"[\u0400-\u04FF]"),
    "latin": re.compile(r"[A-Za-z]"),
    "arabic": re.compile(r"[\u0600-\u06FF]"),
    "cjk": re.compile(r"[\u4E00-\u9FFF]"),
}


def parse_alphabets(raw: str | None) -> list[str]:
    """'Latin, cyrillic,foo' -> ['latin', 'cyrillic']. Регистр не важен, повторы убираются."""
    names = (a.strip().lower() for a in (raw or "").split(","))
    return list(dict.fromkeys(a for a in names if a in SCRIPT_PATTERNS))


@router.message(Command("setalphabet"), HasRole("admin"))
async def set_alphabet(message: Message, command: CommandObject, lang: str = "ru") -> None:
    allowed = parse_alphabets(command.args)
    if not allowed:
        # Раньше подсказка была «/setalphabet <cyrillic|...>» и ломала HTML-разметку.
        await message.answer(t(lang, "setalphabet_usage", options=" | ".join(SCRIPT_PATTERNS)))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "alphabets", {"enabled": True, "allowed": allowed})
    await message.answer(t(lang, "setalphabet_done", alphabets=", ".join(allowed)))


async def check_alphabet(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    cfg = chat_settings.get("alphabets", {})
    if not message.text or not cfg.get("enabled") or is_privileged(chat_user_role):
        return False
    letters = [c for c in message.text if unicodedata.category(c).startswith("L")]
    if not letters:
        return False
    allowed_patterns = [SCRIPT_PATTERNS[a] for a in cfg.get("allowed", []) if a in SCRIPT_PATTERNS]
    if not allowed_patterns:
        return False
    if any(any(p.match(c) for p in allowed_patterns) for c in letters):
        return False
    await delete_message_safely(message)
    return True
