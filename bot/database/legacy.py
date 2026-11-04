"""
Идемпотентные шаги схемы, которые до Alembic выполнялись при каждом старте (issue #13).

Вызываются только из базовой ревизии 0001_baseline, чтобы базы, созданные раньше через
create_all, догнали актуальную схему. Не меняйте этот модуль: любые новые изменения
схемы оформляйте отдельной ревизией (`alembic revision -m "..."`).
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)

# Индексы под частые запросы (issue #13).
INDEXES_DDL = (
    # /stats, лог-канал, проверка «был ли пользователь под санкциями» (privacy_service).
    "CREATE INDEX IF NOT EXISTS ix_audit_log_chat_id_created_at ON audit_log (chat_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_audit_log_target_user_id ON audit_log (target_user_id)",
    # Загрузка списка запрещённых слов чата.
    "CREATE INDEX IF NOT EXISTS ix_banned_words_chat_id ON banned_words (chat_id)",
)

# Колонки chat_users: активность и выход по чату (issue #47), ожидание одобрения (issue #50).
CHAT_USERS_DDL = (
    "ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ",
    "ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS left_at TIMESTAMPTZ",
    "ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS pending_approval BOOLEAN NOT NULL DEFAULT FALSE",
    "CREATE INDEX IF NOT EXISTS ix_chat_users_user_id ON chat_users (user_id)",
)

BOT_CLONES_DDL = (
    "ALTER TABLE bot_clones ADD COLUMN IF NOT EXISTS bot_id BIGINT",
    "ALTER TABLE bot_clones ADD COLUMN IF NOT EXISTS token_encrypted TEXT",
    "ALTER TABLE bot_clones ADD COLUMN IF NOT EXISTS token_hash VARCHAR(64)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_bot_clones_token_hash ON bot_clones (token_hash)",
)

# Рассылки: какой бот отправляет (issue #10).
RECURRING_DDL = ("ALTER TABLE recurring_messages ADD COLUMN IF NOT EXISTS bot_id BIGINT",)


def run_all(conn: Connection) -> None:
    migrate_bot_clones(conn)
    _execute_all(conn, RECURRING_DDL)
    migrate_members_and_stats(conn)
    _execute_all(conn, INDEXES_DDL)


def _execute_all(conn: Connection, statements: tuple[str, ...]) -> None:
    for ddl in statements:
        conn.execute(text(ddl))


def migrate_members_and_stats(conn: Connection) -> None:
    """issue #47: group_stats.date была timestamptz и сравнивалась с date — переводим в DATE."""
    _execute_all(conn, CHAT_USERS_DDL)

    data_type = conn.execute(text(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'group_stats' AND column_name = 'date'"
    )).scalar()
    if data_type and data_type != "date":
        conn.execute(text(
            "ALTER TABLE group_stats ALTER COLUMN date TYPE DATE USING (date AT TIME ZONE 'UTC')::date"
        ))
        logger.info("group_stats.date: %s -> date", data_type)


def migrate_bot_clones(conn: Connection) -> None:
    """
    issue #6: старая схема с колонкой `token` (открытым текстом) — токены шифруются,
    колонка удаляется.
    """
    from bot.services import clone_crypto  # локально: избегаем циклического импорта

    _execute_all(conn, BOT_CLONES_DDL)

    has_plain_column = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'bot_clones' AND column_name = 'token'"
    )).first()
    if not has_plain_column:
        return

    rows = conn.execute(text("SELECT id, token FROM bot_clones WHERE token IS NOT NULL")).all()
    if rows and not clone_crypto.is_configured():
        logger.error(
            "В bot_clones есть %d токенов в открытом виде. Задайте CLONE_ENCRYPTION_KEY и "
            "перезапустите бота, чтобы они были зашифрованы.", len(rows),
        )
        return

    for row_id, token in rows:
        conn.execute(
            text("UPDATE bot_clones SET token_encrypted = :enc, token_hash = :hash WHERE id = :id"),
            {"enc": clone_crypto.encrypt_token(token), "hash": clone_crypto.token_fingerprint(token), "id": row_id},
        )
    conn.execute(text("ALTER TABLE bot_clones DROP COLUMN token"))
    logger.info("bot_clones: зашифровано токенов: %d, открытая колонка удалена", len(rows))
