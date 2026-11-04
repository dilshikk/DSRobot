"""user_message_stats: дневной счётчик сообщений по участнику (issue #92).

Нужен для топа самых активных участников в /stats. Отдельная таблица, а не колонка
в group_stats: строка на (чат, пользователь, день), инкремент — атомарный upsert.

Revision ID: 0003_user_message_stats
Revises: 0002_chat_settings_jsonb
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_user_message_stats"
down_revision = "0002_chat_settings_jsonb"
branch_labels = None
depends_on = None

# Таблица описана здесь явно (как в 0001), чтобы ревизия не зависела от будущих правок models.py.
metadata = sa.MetaData()

sa.Table(
    "user_message_stats", metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
    sa.Column("user_id", sa.BigInteger(), nullable=False),
    sa.Column("date", sa.Date(), nullable=False),
    sa.Column("messages_count", sa.Integer(), nullable=False),
    sa.UniqueConstraint("chat_id", "user_id", "date", name="uq_chat_user_date"),
    # Топ за период: WHERE chat_id = ? AND date BETWEEN ? AND ?
    sa.Index("ix_user_message_stats_chat_date", "chat_id", "date"),
    # /forget и /forgetme удаляют строки пользователя.
    sa.Index("ix_user_message_stats_user", "user_id"),
)


def upgrade() -> None:
    metadata.create_all(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.drop_table("user_message_stats")
