"""
Точка входа. Запуск: python -m bot.main (или через Docker, см. docker-compose.yml).

По умолчанию используется long polling — самый простой вариант для локального
запуска/разработки. Для продакшна замените start_polling на set_webhook + aiohttp
web-сервер (см. README.md, раздел "Переход на Webhook").
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import settings
from bot.database import init_models
from bot.handlers import register_all_routers
from bot.handlers.welcome import captcha as captcha_handler
from bot.handlers.chat import recurring_messages as recurring_handler
from bot.middlewares.antiflood import AntiFloodMiddleware
from bot.middlewares.chat_context import ChatContextMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.services.scheduler import scheduler, start as start_scheduler

logging.basicConfig(level=settings.log_level, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("bot.main")


async def main() -> None:
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Middleware Layer (см. архитектуру): порядок важен — сначала контекст чата
    # (роль, настройки), затем throttling команд, затем anti-flood для обычных сообщений.
    dp.message.middleware(ChatContextMiddleware())
    dp.message.middleware(ThrottlingMiddleware())
    dp.message.middleware(AntiFloodMiddleware())

    register_all_routers(dp)

    logger.info("Инициализация базы данных...")
    await init_models()

    captcha_handler.bind_bot(bot)
    recurring_handler.bind_bot(bot)
    start_scheduler()

    logger.info("Бот запущен, начинаю polling...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
