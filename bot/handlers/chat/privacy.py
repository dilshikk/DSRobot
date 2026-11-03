"""
Remove user-data from group (/forget), Remove user-data from bot, User privacy mode.
GDPR-подобная функциональность: удаление данных о пользователе. Варны и история
санкций сохраняются, иначе /forget сбрасывал бы наказания (issue #36).
"""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.privacy_service import forget_user
from bot.services.settings_service import update_settings

router = Router(name="privacy")


@router.message(Command("forget"))
async def forget_me_in_group(message) -> None:
    """Удаляет данные вызвавшего пользователя из ЭТОГО чата."""
    async with SessionFactory() as session:
        kept = await forget_user(session, message.from_user.id, message.chat.id)
        await session.commit()
    await message.answer(
        "\u2705 Ваши данные в этом чате удалены."
        + (" Варны и история санкций сохранены для модераторов." if kept else "")
    )


@router.message(Command("forgetme"))
async def forget_me_everywhere(message) -> None:
    """Удаляет данные пользователя из всех чатов, где известен боту (только в личке боту)."""
    if message.chat.type != "private":
        await message.answer("Эту команду нужно вызвать в личных сообщениях боту.")
        return
    async with SessionFactory() as session:
        kept = await forget_user(session, message.from_user.id)
        await session.commit()
    await message.answer(
        "\u2705 Ваши данные удалены из базы бота во всех чатах."
        + (" Варны и история санкций сохранены для модераторов чатов." if kept else "")
    )


@router.message(Command("privacymode"), HasRole("admin"))
async def toggle_privacy_mode(message, chat_settings: dict) -> None:
    new_state = not chat_settings.get("privacy", {}).get("user_privacy_mode", True)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "privacy", {"user_privacy_mode": new_state})
    await message.answer(
        f"User privacy mode: {'включён' if new_state else 'выключен'} "
        f"({'бот хранит минимум данных о участниках' if new_state else 'бот хранит расширенные данные для аналитики'})"
    )
