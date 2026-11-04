from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, pool_pre_ping=True, echo=False)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config() -> Config:
    """Конфиг Alembic без alembic.ini: путь к миграциям не зависит от текущей папки."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def _upgrade_to_head(connection: Connection) -> None:
    config = alembic_config()
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


async def init_models() -> None:
    """
    Применяет Alembic-миграции до последней версии (issue #13).
    Базы, созданные раньше через create_all, подхватываются базовой ревизией 0001.
    """
    async with engine.begin() as conn:
        await conn.run_sync(_upgrade_to_head)
    logger.info("Схема БД актуальна")


async def close_db() -> None:
    """Закрывает пул соединений PostgreSQL при остановке бота (issue #13)."""
    await engine.dispose()


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
