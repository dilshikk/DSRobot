"""
Remove user-data from group (/forget), Remove user-data from bot, User privacy mode.
GDPR-подобная функциональность: удаление всех записей о пользователе (варны, роли, заметки).
"""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from sqlalchemy import delete

from bot.database import SessionFactory
from bot.database.models import AuditLog, ChatUser
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings

router = Router(name="privacy")


@router.message(Command("forget"))
async def forget_me_in_group(message) -> None:
    """Удаляет данные вызвавшего пользователя из ЭТОГО чата."""
    async with SessionFactory() as session:
        await session.execute(delete(ChatUser).where(
            ChatUser.chat_id == message.chat.id, ChatUser.user_id == message.from_user.id
        ))
        await session.execute(delete(AuditLog).where(
            AuditLog.chat_id == message.chat.id, AuditLog.target_user_id == message.from_user.id
        ))
        await session.commit()
    await message.answer("\u2705 Ваши данные в этом чате удалены (варны, роль, история санкций).")


@router.message(Command("forgetme"))
async def forget_me_everywhere(message) -> None:
    """Удаляет данные пользователя из всех чатов, где известен боту (только в личке боту)."""
    if message.chat.type != "private":
        await message.answer("Эту команду нужно вызвать в личных сообщениях боту.")
        return
    async with SessionFactory() as session:
        await session.execute(delete(ChatUser).where(ChatUser.user_id == message.from_user.id))
        await session.execute(delete(AuditLog).where(AuditLog.target_user_id == message.from_user.id))
        await session.commit()
    await message.answer("\u2705 Все ваши данные удалены из базы бота во всех чатах.")


@router.message(Command("privacymode"), HasRole("admin"))
async def toggle_privacy_mode(message, chat_settings: dict) -> None:
    new_state = not chat_settings.get("privacy", {}).get("user_privacy_mode", True)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "privacy", {"user_privacy_mode": new_state})
    await message.answer(
        f"User privacy mode: {'включён' if new_state else 'выключен'} "
        f"({'бот хранит минимум данных о участниках' if new_state else 'бот хранит расширенные данные для аналитики'})"
    )
