from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine

from bot.config import settings
from bot.database.models import Base

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, pool_pre_ping=True, echo=False)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_models() -> None:
    """Создаёт таблицы, если их ещё нет. Для продакшна замените на Alembic-миграции (issue #13)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_bot_clones(conn)
        await _migrate_recurring_messages(conn)


async def _migrate_recurring_messages(conn: AsyncConnection) -> None:
    """
    Временная идемпотентная миграция (issue #10), пока нет Alembic.
    create_all не добавляет колонки в существующие таблицы, а без bot_id
    /addrecurring и восстановление рассылок при старте падают.
    """
    await conn.execute(text("ALTER TABLE recurring_messages ADD COLUMN IF NOT EXISTS bot_id BIGINT"))


async def _migrate_bot_clones(conn: AsyncConnection) -> None:
    """
    Временная идемпотентная миграция bot_clones (issue #6), пока нет Alembic.
    create_all не меняет уже существующие таблицы, поэтому старая схема с колонкой
    `token` (открытым текстом) переводится сюда вручную: токены шифруются, колонка удаляется.
    """
    from bot.services import clone_crypto  # локально: избегаем циклического импорта

    for ddl in (
        "ALTER TABLE bot_clones ADD COLUMN IF NOT EXISTS bot_id BIGINT",
        "ALTER TABLE bot_clones ADD COLUMN IF NOT EXISTS token_encrypted TEXT",
        "ALTER TABLE bot_clones ADD COLUMN IF NOT EXISTS token_hash VARCHAR(64)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_bot_clones_token_hash ON bot_clones (token_hash)",
    ):
        await conn.execute(text(ddl))

    has_plain_column = (await conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'bot_clones' AND column_name = 'token'"
    ))).first()
    if not has_plain_column:
        return

    rows = (await conn.execute(text("SELECT id, token FROM bot_clones WHERE token IS NOT NULL"))).all()
    if rows and not clone_crypto.is_configured():
        logger.error(
            "В bot_clones есть %d токенов в открытом виде. Задайте CLONE_ENCRYPTION_KEY и "
            "перезапустите бота, чтобы они были зашифрованы.", len(rows),
        )
        return

    for row_id, token in rows:
        await conn.execute(
            text("UPDATE bot_clones SET token_encrypted = :enc, token_hash = :hash WHERE id = :id"),
            {"enc": clone_crypto.encrypt_token(token), "hash": clone_crypto.token_fingerprint(token), "id": row_id},
        )
    await conn.execute(text("ALTER TABLE bot_clones DROP COLUMN token"))
    logger.info("bot_clones: зашифровано токенов: %d, открытая колонка удалена", len(rows))


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
