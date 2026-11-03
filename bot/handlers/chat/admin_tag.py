"""@Admin — вызов админов с cooldown, чтобы не превращалось в спам."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import ChatMemberAdministrator, ChatMemberOwner

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.cache import redis
from bot.services.settings_service import update_settings

router = Router(name="admin_tag")

MAX_COOLDOWN_SEC = 86400


@router.message(Command("admincooldown"), HasRole("admin"))
async def set_admin_cooldown(message, command: CommandObject) -> None:
    raw = (command.args or "").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= MAX_COOLDOWN_SEC:
        await message.answer(f"Использование: /admincooldown СЕКУНДЫ (1-{MAX_COOLDOWN_SEC})")
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "tag_admin", {"cooldown_sec": int(raw)})
    await message.answer(f"\u2705 Вызов /admin не чаще раза в {raw} с.")


@router.message(Command("admin"))
async def call_admin(message, chat_settings: dict) -> None:
    cooldown = chat_settings.get("tag_admin", {}).get("cooldown_sec", 300)
    key = f"admincall:{message.chat.id}"
    if await redis.exists(key):
        await message.answer("\u23f3 Вызов админов уже был недавно, подождите.")
        return
    await redis.set(key, 1, ex=cooldown)

    admins = await message.bot.get_chat_administrators(message.chat.id)
    mentions = [a.user.mention_html() for a in admins
                if isinstance(a, (ChatMemberAdministrator, ChatMemberOwner)) and not a.user.is_bot]
    text = "\U0001f6a8 Требуется внимание администратора: " + " ".join(mentions[:10])
    await message.reply(text, parse_mode="HTML")
