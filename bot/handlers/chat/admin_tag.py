"""@Admin — вызов админов с cooldown, чтобы не превращалось в спам."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import ChatMemberAdministrator, ChatMemberOwner

from bot.services.cache import redis

router = Router(name="admin_tag")


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
