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
from bot.middlewares.moderation_pipeline import ModerationPipelineMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.services.scheduler import scheduler, start as start_scheduler

logging.basicConfig(level=settings.log_level, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("bot.main")


def setup_middlewares(dp: Dispatcher) -> None:
    """
    Middleware Layer. Порядок важен: сначала контекст чата (роль, настройки), затем
    throttling команд, anti-flood и единая цепочка авто-модерации (issue #1).

    Используются OUTER-middleware: inner-middleware в aiogram 3 вызываются только ПОСЛЕ
    того, как фильтры хендлера прошли. Из-за этого фильтр HasRole не видел
    chat_user_role, а сообщения без подходящего хендлера (фото, правки) вообще не
    проходили модерацию (issue #7).
    """
    dp.message.outer_middleware(ChatContextMiddleware())
    dp.message.outer_middleware(ThrottlingMiddleware())
    dp.message.outer_middleware(AntiFloodMiddleware())
    dp.message.outer_middleware(ModerationPipelineMiddleware())

    # Правка сообщения не должна обходить фильтры (issue #7). Anti-flood и throttling
    # для правок не нужны: правка не создаёт новое сообщение.
    dp.edited_message.outer_middleware(ChatContextMiddleware())
    dp.edited_message.outer_middleware(ModerationPipelineMiddleware())


async def main() -> None:
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    setup_middlewares(dp)
    register_all_routers(dp)

    logger.info("Инициализация базы данных...")
    await init_models()

    captcha_handler.bind_bot(bot)
    recurring_handler.bind_bot(bot)
    start_scheduler()

    # По умолчанию aiogram подписывается только на типы апдейтов, для которых есть
    # хендлеры. Для edited_message хендлеров нет — работает только middleware,
    # поэтому тип нужно запросить явно.
    allowed_updates = sorted(set(dp.resolve_used_update_types()) | {"edited_message"})

    logger.info("Бот запущен, начинаю polling...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=allowed_updates)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
