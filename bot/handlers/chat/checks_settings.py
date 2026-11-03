"""
Checks settings: самопроверка бота — есть ли у него нужные права
администратора в чате (нужно для модерации/капчи/night-mode и т.п.).
Ответы — на языке чата (issue #12).
"""
from aiogram import Router
from aiogram.filters import Command

from bot.utils.i18n import t

router = Router(name="checks_settings")

REQUIRED_RIGHTS = ("can_delete_messages", "can_restrict_members", "can_invite_users", "can_pin_messages")


def missing_rights_text(lang: str, missing: list[str]) -> str:
    """Раньше в чат выводились технические имена (can_pin_messages) — теперь понятные названия."""
    if not missing:
        return t(lang, "checkperms_ok")
    return t(lang, "checkperms_missing", rights=", ".join(t(lang, f"right_{r}") for r in missing))


@router.message(Command("checkperms"))
async def check_perms(message, lang: str = "ru") -> None:
    member = await message.bot.get_chat_member(message.chat.id, message.bot.id)
    missing = [r for r in REQUIRED_RIGHTS if not getattr(member, r, False)]
    await message.answer(missing_rights_text(lang, missing))
