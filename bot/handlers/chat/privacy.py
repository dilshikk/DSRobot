"""
Remove user-data from group (/forget), Remove user-data from bot, User privacy mode.
GDPR-подобная функциональность: удаление всех записей о пользователе (варны, роли, заметки).
Ответы — на языке чата (issue #12); в личке — на языке Telegram-клиента.
"""
from aiogram import Router
from aiogram.filters import Command
from sqlalchemy import delete

from bot.database import SessionFactory
from bot.database.models import AuditLog, ChatUser
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings
from bot.utils.i18n import t

router = Router(name="privacy")


def privacy_mode_text(lang: str, enabled: bool) -> str:
    return t(lang, "privacy_mode_on" if enabled else "privacy_mode_off")


@router.message(Command("forget"))
async def forget_me_in_group(message, lang: str = "ru") -> None:
    """Удаляет данные вызвавшего пользователя из ЭТОГО чата."""
    if not message.from_user:
        return
    async with SessionFactory() as session:
        await session.execute(delete(ChatUser).where(
            ChatUser.chat_id == message.chat.id, ChatUser.user_id == message.from_user.id
        ))
        await session.execute(delete(AuditLog).where(
            AuditLog.chat_id == message.chat.id, AuditLog.target_user_id == message.from_user.id
        ))
        await session.commit()
    await message.answer(t(lang, "forget_done"))


@router.message(Command("forgetme"))
async def forget_me_everywhere(message, lang: str = "ru") -> None:
    """Удаляет данные пользователя из всех чатов, где известен боту (только в личке боту)."""
    if message.chat.type != "private":
        await message.answer(t(lang, "forgetme_private_only"))
        return
    async with SessionFactory() as session:
        await session.execute(delete(ChatUser).where(ChatUser.user_id == message.from_user.id))
        await session.execute(delete(AuditLog).where(AuditLog.target_user_id == message.from_user.id))
        await session.commit()
    await message.answer(t(lang, "forgetme_done"))


@router.message(Command("privacymode"), HasRole("admin"))
async def toggle_privacy_mode(message, chat_settings: dict, lang: str = "ru") -> None:
    new_state = not chat_settings.get("privacy", {}).get("user_privacy_mode", True)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "privacy", {"user_privacy_mode": new_state})
    await message.answer(privacy_mode_text(lang, new_state))
