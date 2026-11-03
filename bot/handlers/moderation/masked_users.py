"""
Masked users settings: обнаружение замаскированных ссылок — text_link-энтити, где видимый
текст не совпадает с реальным доменом (частый способ обхода link-фильтра).
"""
from urllib.parse import urlparse

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings

router = Router(name="masked_users")


@router.message(Command("maskedlinks"), HasRole("admin"))
async def toggle_masked(message: Message, chat_settings: dict) -> None:
    new_state = not chat_settings.get("blocks", {}).get("masked_links", False)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "blocks", {"masked_links": new_state})
    await message.answer(f"Фильтр замаскированных ссылок: {'включён' if new_state else 'выключен'}")


@router.message(F.entities, ~F.text.startswith("/"))
async def detect_masked_links(message: Message, chat_settings: dict, chat_user_role: str = "member") -> None:
    if not chat_settings.get("blocks", {}).get("masked_links") or chat_user_role in ("admin", "owner", "developer"):
        return
    for entity in message.entities or []:
        if entity.type == "text_link" and entity.url:
            visible = (message.text or "")[entity.offset: entity.offset + entity.length]
            real_domain = urlparse(entity.url).netloc
            if real_domain and real_domain.lower() not in visible.lower():
                try:
                    await message.delete()
                except Exception:
                    pass
                return
