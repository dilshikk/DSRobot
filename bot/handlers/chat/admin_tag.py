"""@Admin — вызов админов с cooldown, чтобы не превращалось в спам. Ответы — на языке чата (issue #12)."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import ChatMemberAdministrator, ChatMemberOwner

from bot.services.cache import redis
from bot.utils.i18n import t

router = Router(name="admin_tag")

MAX_MENTIONS = 10


@router.message(Command("admin"))
async def call_admin(message, chat_settings: dict, lang: str = "ru") -> None:
    cooldown = chat_settings.get("tag_admin", {}).get("cooldown_sec", 300)
    key = f"admincall:{message.chat.id}"
    if await redis.exists(key):
        await message.answer(t(lang, "admin_call_cooldown"))
        return
    await redis.set(key, 1, ex=cooldown)

    admins = await message.bot.get_chat_administrators(message.chat.id)
    mentions = [a.user.mention_html() for a in admins
                if isinstance(a, (ChatMemberAdministrator, ChatMemberOwner)) and not a.user.is_bot]
    await message.reply(t(lang, "admin_call", mentions=" ".join(mentions[:MAX_MENTIONS])), parse_mode="HTML")
