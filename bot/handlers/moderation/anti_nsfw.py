"""
Anti-NSFW: точка интеграции с внешним классификатором изображений
(например Sightengine / AWS Rekognition / собственная модель).
Здесь — включение/выключение фичи и заготовка вызова; сам ML-вызов — TODO,
т.к. требует API-ключ конкретного провайдера, который не специфицирован в ТЗ.
Проверка вызывается из moderation_pipeline. Ответы — на языке чата (issue #12).
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings
from bot.utils.i18n import t, toggle_text

router = Router(name="anti_nsfw")


def nsfw_toggle_text(lang: str, enabled: bool) -> str:
    text = toggle_text(lang, "feature_anti_nsfw", enabled)
    return f"{text}\n{t(lang, 'nsfw_provider_missing')}" if enabled else text


@router.message(Command("antinsfw"), HasRole("admin"))
async def toggle_nsfw(message: Message, chat_settings: dict, lang: str = "ru") -> None:
    new_state = not chat_settings.get("anti_nsfw", {}).get("enabled", False)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "anti_nsfw", {"enabled": new_state})
    await message.answer(nsfw_toggle_text(lang, new_state))


async def check_nsfw(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    if not message.photo or not chat_settings.get("anti_nsfw", {}).get("enabled"):
        return False
    # TODO: скачать message.photo[-1].file_id через bot.get_file и отправить
    # в выбранный NSFW-классификатор (см. docstring модуля), удалить при положительном срабатывании.
    return False
