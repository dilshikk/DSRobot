"""Alphabets: ограничение сообщений только разрешёнными алфавитами (борьба с непонятным спамом/флудом)."""
import re
import unicodedata

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings

router = Router(name="alphabets")

SCRIPT_PATTERNS = {
    "cyrillic": re.compile(r"[\u0400-\u04FF]"),
    "latin": re.compile(r"[A-Za-z]"),
    "arabic": re.compile(r"[\u0600-\u06FF]"),
    "cjk": re.compile(r"[\u4E00-\u9FFF]"),
}


@router.message(Command("setalphabet"), HasRole("admin"))
async def set_alphabet(message: Message, command: CommandObject) -> None:
    allowed = [a.strip() for a in (command.args or "").split(",") if a.strip() in SCRIPT_PATTERNS]
    if not allowed:
        await message.answer(f"Использование: /setalphabet <{'|'.join(SCRIPT_PATTERNS)}>[,...]")
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "alphabets", {"enabled": True, "allowed": allowed})
    await message.answer(f"\u2705 Разрешённые алфавиты: {', '.join(allowed)}")


@router.message(F.text, ~F.text.startswith("/"))
async def enforce_alphabet(message: Message, chat_settings: dict, chat_user_role: str = "member") -> None:
    cfg = chat_settings.get("alphabets", {})
    if not cfg.get("enabled") or chat_user_role in ("admin", "owner", "developer"):
        return
    letters = [c for c in (message.text or "") if unicodedata.category(c).startswith("L")]
    if not letters:
        return
    allowed_patterns = [SCRIPT_PATTERNS[a] for a in cfg.get("allowed", []) if a in SCRIPT_PATTERNS]
    if not allowed_patterns:
        return
    if not any(any(p.match(c) for p in allowed_patterns) for c in letters):
        try:
            await message.delete()
        except Exception:
            pass
