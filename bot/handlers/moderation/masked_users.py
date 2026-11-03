"""
Masked users settings: обнаружение замаскированных ссылок — text_link-энтити, где видимый
текст не совпадает с реальным доменом (частый способ обхода link-фильтра).
Проверка вызывается из moderation_pipeline. Ответы — на языке чата (issue #12).
"""
from urllib.parse import urlparse

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings
from bot.utils.i18n import toggle_text
from bot.utils.permissions import is_privileged
from bot.utils.telegram import delete_message_safely

router = Router(name="masked_users")


@router.message(Command("maskedlinks"), HasRole("admin"))
async def toggle_masked(message: Message, chat_settings: dict, lang: str = "ru") -> None:
    new_state = not chat_settings.get("blocks", {}).get("masked_links", False)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "blocks", {"masked_links": new_state})
    await message.answer(toggle_text(lang, "feature_masked_links", new_state))


async def check_masked_links(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    if not message.entities or not chat_settings.get("blocks", {}).get("masked_links") or is_privileged(chat_user_role):
        return False
    for entity in message.entities:
        if entity.type == "text_link" and entity.url:
            visible = (message.text or "")[entity.offset: entity.offset + entity.length]
            real_domain = urlparse(entity.url).netloc
            if real_domain and real_domain.lower() not in visible.lower():
                await delete_message_safely(message)
                return True
    return False
