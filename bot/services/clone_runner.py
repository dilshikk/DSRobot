"""
Запуск клонов (issue #6).

Все клоны работают в том же процессе и на том же Dispatcher, что и основной бот:
`dp.start_polling(main_bot, *clone_bots)`. Отдельный оркестратор не нужен.
Список клонов читается при старте, поэтому новый или удалённый клон
вступает в силу после перезапуска основного бота.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNotFound, TelegramUnauthorizedError
from aiogram.types import User
from aiogram.utils.token import TokenValidationError
from sqlalchemy import select

from bot.database import SessionFactory
from bot.database.models import BotClone
from bot.services import clone_crypto

logger = logging.getLogger(__name__)


def create_bot(token: str) -> Bot:
    """Единые настройки для основного бота и клонов."""
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


async def fetch_bot_identity(token: str) -> User | None:
    """
    Проверяет токен через getMe. Возвращает None, если формат неверный или Telegram
    отклонил токен. Сетевые ошибки пробрасываются: это не повод считать токен плохим.
    """
    try:
        bot = Bot(token=token)
    except TokenValidationError:
        return None
    try:
        return await bot.get_me()
    except (TelegramUnauthorizedError, TelegramNotFound):
        return None
    finally:
        await bot.session.close()


async def load_clone_bots(main_bot_id: int) -> list[Bot]:
    """Расшифровывает и проверяет активные клоны. Нерабочие пропускаются с записью в лог."""
    if not clone_crypto.is_configured():
        logger.info("CLONE_ENCRYPTION_KEY не задан, клоны не запускаются")
        return []

    bots: list[Bot] = []
    async with SessionFactory() as session:
        rows = (await session.execute(select(BotClone).where(BotClone.is_active.is_(True)))).scalars().all()
        for row in rows:
            try:
                token = clone_crypto.decrypt_token(row.token_encrypted)
            except clone_crypto.InvalidToken:
                logger.error("Клон #%s: не удалось расшифровать токен (сменился CLONE_ENCRYPTION_KEY?)", row.id)
                continue

            bot = create_bot(token)
            try:
                me = await bot.get_me()
            except TelegramUnauthorizedError:
                # Токен отозван в @BotFather: выключаем, чтобы не пытаться при каждом старте.
                logger.warning("Клон #%s: токен отозван, клон выключен", row.id)
                row.is_active = False
                await bot.session.close()
                continue
            except Exception:
                logger.exception("Клон #%s: не удалось проверить токен, пропускаю", row.id)
                await bot.session.close()
                continue

            if me.id == main_bot_id:
                await bot.session.close()
                continue

            row.bot_id, row.bot_username = me.id, me.username or ""
            bots.append(bot)
        await session.commit()

    logger.info("Запущено клонов: %d", len(bots))
    return bots
