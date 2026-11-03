"""Bot help (how to use) + /start. Ответы — на языке чата (issue #12)."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.utils.i18n import t

router = Router(name="start_help")


@router.message(Command("start"))
async def cmd_start(message: Message, lang: str = "ru") -> None:
    await message.answer(t(lang, "help_text"))


@router.message(Command("help"))
async def cmd_help(message: Message, lang: str = "ru") -> None:
    await message.answer(t(lang, "help_sections"), parse_mode="HTML")


@router.message(Command("commands"))
async def cmd_list(message: Message, lang: str = "ru") -> None:
    await message.answer(t(lang, "commands_list"), parse_mode="HTML")
