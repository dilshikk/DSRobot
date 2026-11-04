"""
Окружение Alembic (issue #13).

Два режима:
- бот при старте передаёт готовое соединение через config.attributes["connection"]
  (см. bot/database/engine.py) — миграции идут в той же транзакции;
- CLI (`alembic upgrade head`) — создаём свой async-движок по настройкам из .env.
"""
from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from bot.config import settings
from bot.database.models import Base

target_metadata = Base.metadata


def run_with_connection(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(run_with_connection)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    shared = context.config.attributes.get("connection")
    if shared is None:
        asyncio.run(run_online())
    else:
        run_with_connection(shared)
