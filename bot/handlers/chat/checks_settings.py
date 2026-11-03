"""
Checks settings: периодическая самопроверка бота — есть ли у него нужные права
администратора в чате (нужно для модерации/капчи/night-mode и т.п.).
"""
from aiogram import Router
from aiogram.filters import Command

router = Router(name="checks_settings")

REQUIRED_RIGHTS = ["can_delete_messages", "can_restrict_members", "can_invite_users", "can_pin_messages"]


@router.message(Command("checkperms"))
async def check_perms(message) -> None:
    member = await message.bot.get_chat_member(message.chat.id, message.bot.id)
    missing = [r for r in REQUIRED_RIGHTS if not getattr(member, r, False)]
    if not missing:
        await message.answer("\u2705 У бота есть все необходимые права.")
    else:
        await message.answer("\u26a0\ufe0f Боту не хватает прав: " + ", ".join(missing))
