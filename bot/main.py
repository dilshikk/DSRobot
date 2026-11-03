"""
Точка входа. Запуск: python -m bot.main (или через Docker, см. docker-compose.yml).

По умолчанию используется long polling — самый простой вариант для локального
запуска/разработки. Для продакшна замените start_polling на set_webhook + aiohttp
web-сервер (см. README.md, раздел "Переход на Webhook").

Клоны (issue #6) работают в этом же процессе: один Dispatcher опрашивает несколько ботов.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher

from bot.config import settings
from bot.database import init_models
from bot.handlers import register_all_routers
from bot.middlewares.antiflood import AntiFloodMiddleware
from bot.middlewares.chat_context import ChatContextMiddleware
from bot.middlewares.moderation_pipeline import ModerationPipelineMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.services import bot_registry
from bot.services.clone_runner import create_bot, load_clone_bots
from bot.services.recurring import restore_recurring_jobs
from bot.services.scheduler import scheduler, start as start_scheduler

logging.basicConfig(level=settings.log_level, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("bot.main")


def setup_sentry() -> None:
    """
    Подключает Sentry, если задан SENTRY_DSN (issue #9). Интеграция с logging
    включена по умолчанию: всё, что пишется через logger.error/logger.exception,
    уходит в Sentry как событие, а warning-и сохраняются как breadcrumbs.
    """
    if not settings.sentry_dsn:
        return
    import sentry_sdk

    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.0, send_default_pii=False)
    logger.info("Sentry подключён")


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
    setup_sentry()
    bot = create_bot(settings.bot_token)
    dp = Dispatcher()

    setup_middlewares(dp)
    register_all_routers(dp)

    logger.info("Инициализация базы данных...")
    await init_models()

    clone_bots = await load_clone_bots(main_bot_id=bot.id)
    all_bots = [bot, *clone_bots]

    # Реестр заполняется ДО запуска планировщика: задачи, пропущенные во время простоя
    # (например, таймауты капчи), выполнятся сразу после старта и должны найти своего бота.
    bot_registry.register(bot, main=True)
    for clone in clone_bots:
        bot_registry.register(clone)
    start_scheduler()
    restored = await restore_recurring_jobs()
    logger.info("Активных рассылок: %d", restored)

    # По умолчанию aiogram подписывается только на типы апдейтов, для которых есть
    # хендлеры. Для edited_message хендлеров нет — работает только middleware,
    # поэтому тип нужно запросить явно.
    allowed_updates = sorted(set(dp.resolve_used_update_types()) | {"edited_message"})

    logger.info("Бот запущен (клонов: %d), начинаю polling...", len(clone_bots))
    try:
        for b in all_bots:
            await b.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(*all_bots, allowed_updates=allowed_updates)
    finally:
        scheduler.shutdown(wait=False)
        for b in all_bots:
            await b.session.close()


if __name__ == "__main__":
    asyncio.run(main())
