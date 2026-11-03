"""Media blocks: photo / video / sticker / gif / voice / document. Проверка вызывается из moderation_pipeline."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.settings_service import update_settings
from bot.utils.permissions import is_privileged

router = Router(name="media_blocks")

MEDIA_MAP = {
    "photo": lambda m: bool(m.photo),
    "video": lambda m: bool(m.video),
    "sticker": lambda m: bool(m.sticker),
    "gif": lambda m: bool(m.animation),
    "voice": lambda m: bool(m.voice),
    "document": lambda m: bool(m.document),
}


@router.message(Command("blockmedia"), HasRole("admin"))
async def block_media(message: Message, command: CommandObject) -> None:
    key = (command.args or "").strip().lower()
    if key not in MEDIA_MAP:
        await message.answer(f"Использование: /blockmedia <{'|'.join(MEDIA_MAP)}>")
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "media_blocks", {key: True})
    await message.answer(f"\u2705 Медиа-блок «{key}» включён.")


async def check_media_block(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    if is_privileged(chat_user_role):
        return False
    blocks = chat_settings.get("media_blocks", {})
    for kind, check in MEDIA_MAP.items():
        if blocks.get(kind) and check(message):
            try:
                await message.delete()
            except Exception:
                pass
            return True
    return False
