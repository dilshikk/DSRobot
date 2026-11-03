"""Bot help (how to use) + /start."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.utils.i18n import t

router = Router(name="start_help")


@router.message(Command("start"))
async def cmd_start(message: Message, chat_settings: dict | None = None) -> None:
    lang = "ru"
    await message.answer(t(lang, "help_text"))


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Основные разделы команд</b>\n"
        "/rules — правила чата\n"
        "/ban /mute /kick /warn — модерация (ответом на сообщение)\n"
        "/settings — открыть панель настроек чата\n"
        "/commands — полный список команд по категориям",
        parse_mode="HTML",
    )


@router.message(Command("commands"))
async def cmd_list(message: Message) -> None:
    await message.answer(
        "\U0001f4c2 <b>Категории</b>: modules, moderation, welcome, warns, "
        "antiflood, captcha, blocks, filters, notes, admin, stats, privacy\n"
        "Используйте /help &lt;категория&gt; (заглушка — расширяется по мере роста бота).",
        parse_mode="HTML",
    )
