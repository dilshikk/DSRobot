"""
Anti-NSFW: точка интеграции с внешним классификатором изображений
(например Sightengine / AWS Rekognition / собственная модель).
Здесь — включение/выключение фичи и заготовка вызова; сам ML-вызов — TODO,
т.к. требует API-ключ конкретного провайдера, который не специфицирован в ТЗ.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings

router = Router(name="anti_nsfw")


@router.message(Command("antinsfw"), HasRole("admin"))
async def toggle_nsfw(message: Message, chat_settings: dict) -> None:
    new_state = not chat_settings.get("anti_nsfw", {}).get("enabled", False)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "anti_nsfw", {"enabled": new_state})
    await message.answer(
        f"Anti-NSFW: {'включён' if new_state else 'выключен'}"
        + ("\n\u26a0\ufe0f Требуется подключить провайдера классификации изображений в .env" if new_state else "")
    )


@router.message(F.photo)
async def scan_photo_stub(message: Message, chat_settings: dict) -> None:
    if not chat_settings.get("anti_nsfw", {}).get("enabled"):
        return
    # TODO: скачать message.photo[-1].file_id через bot.get_file и отправить
    # в выбранный NSFW-классификатор (см. docstring модуля), удалить при положительном срабатывании.
    return
