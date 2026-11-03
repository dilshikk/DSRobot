"""
Реестр запущенных ботов: основной + клоны (issue #10).

Отложенные задачи хранятся в Redis и не могут держать объект Bot, поэтому в
аргументах задачи передаётся bot_id, а здесь по нему находится нужный бот.
Так капча и рассылки в чатах клона выполняются от имени клона, а не основного бота.
"""
from __future__ import annotations

from aiogram import Bot

_bots: dict[int, Bot] = {}
_main_bot_id: int | None = None


def register(bot: Bot, *, main: bool = False) -> None:
    global _main_bot_id
    _bots[bot.id] = bot
    if main:
        _main_bot_id = bot.id


def get_bot(bot_id: int | None = None) -> Bot | None:
    """Бот по id. Без id (старые записи) — основной бот. None, если бот не запущен."""
    if bot_id is None:
        bot_id = _main_bot_id
    if bot_id is None:
        return None
    return _bots.get(bot_id)


def clear() -> None:
    """Для тестов."""
    global _main_bot_id
    _bots.clear()
    _main_bot_id = None
