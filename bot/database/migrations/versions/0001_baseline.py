"""Базовая схема (issue #13).

Снимок схемы на момент перехода на Alembic. Таблицы описаны здесь явно, а не через
models.py: модели будут меняться, а эта ревизия должна оставаться неизменной.

Работает и на пустой базе, и на базе, созданной раньше через create_all:
существующие таблицы пропускаются (checkfirst), затем выполняются прежние
идемпотентные шаги из bot/database/legacy.py (колонки, шифрование токенов, индексы).

Revision ID: 0001_baseline
Revises:
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from bot.database import legacy

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

metadata = sa.MetaData()


def _chat_fk() -> sa.ForeignKey:
    return sa.ForeignKey("chats.id", ondelete="CASCADE")


sa.Table(
    "chats", metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
    sa.Column("title", sa.String(255), nullable=False),
    sa.Column("type", sa.String(32), nullable=False),
    sa.Column("lang", sa.String(8), nullable=False),
    sa.Column("utc_offset", sa.Integer(), nullable=False),
    sa.Column("is_active", sa.Boolean(), nullable=False),
    sa.Column("discussion_group_id", sa.BigInteger(), nullable=True),
    sa.Column("log_channel_id", sa.BigInteger(), nullable=True),
    sa.Column("staff_group_id", sa.BigInteger(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
)

sa.Table(
    "chat_settings", metadata,
    sa.Column("chat_id", sa.BigInteger(), _chat_fk(), primary_key=True, autoincrement=False),
    sa.Column("data", sa.JSON(), nullable=False),
)

sa.Table(
    "users", metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
    sa.Column("username", sa.String(64), nullable=True),
    sa.Column("full_name", sa.String(255), nullable=False),
    sa.Column("is_global_banned", sa.Boolean(), nullable=False),
    sa.Column("lang", sa.String(8), nullable=False),
    sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
)

sa.Table(
    "custom_roles", metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("chat_id", sa.BigInteger(), _chat_fk(), nullable=False),
    sa.Column("name", sa.String(64), nullable=False),
    sa.Column("permissions", sa.JSON(), nullable=False),
)

sa.Table(
    "chat_users", metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("chat_id", sa.BigInteger(), _chat_fk(), nullable=False),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sa.Column("role", sa.String(32), nullable=False),
    sa.Column("custom_role_id", sa.Integer(), sa.ForeignKey("custom_roles.id"), nullable=True),
    sa.Column("warns", sa.Integer(), nullable=False),
    sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True),
    sa.Column("banned_until", sa.DateTime(timezone=True), nullable=True),
    sa.Column("approved", sa.Boolean(), nullable=False),
    sa.Column("pending_approval", sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
    sa.UniqueConstraint("chat_id", "user_id", name="uq_chat_user"),
)

sa.Table(
    "command_permissions", metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("chat_id", sa.BigInteger(), _chat_fk(), nullable=False),
    sa.Column("command", sa.String(64), nullable=False),
    sa.Column("min_role", sa.String(32), nullable=False),
    sa.UniqueConstraint("chat_id", "command", name="uq_chat_command"),
)

sa.Table(
    "audit_log", metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("chat_id", sa.BigInteger(), _chat_fk(), nullable=False),
    sa.Column("target_user_id", sa.BigInteger(), nullable=False),
    sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
    sa.Column("action", sa.String(32), nullable=False),
    sa.Column("reason", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
)

sa.Table(
    "banned_words", metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("chat_id", sa.BigInteger(), _chat_fk(), nullable=False),
    sa.Column("word", sa.String(255), nullable=False),
    sa.UniqueConstraint("chat_id", "word", name="uq_chat_word"),
)

sa.Table(
    "recurring_messages", metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("chat_id", sa.BigInteger(), _chat_fk(), nullable=False),
    sa.Column("text", sa.Text(), nullable=False),
    sa.Column("cron_expression", sa.String(64), nullable=False),
    sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("is_active", sa.Boolean(), nullable=False),
    sa.Column("bot_id", sa.BigInteger(), nullable=True),
)

sa.Table(
    "personal_commands", metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("chat_id", sa.BigInteger(), _chat_fk(), nullable=False),
    sa.Column("trigger", sa.String(128), nullable=False),
    sa.Column("response_type", sa.String(16), nullable=False),
    sa.Column("response_content", sa.Text(), nullable=False),
    sa.Column("created_by", sa.BigInteger(), nullable=False),
    sa.UniqueConstraint("chat_id", "trigger", name="uq_chat_trigger"),
)

sa.Table(
    "topic_settings", metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("chat_id", sa.BigInteger(), _chat_fk(), nullable=False),
    sa.Column("topic_id", sa.Integer(), nullable=False),
    sa.Column("name", sa.String(255), nullable=False),
    sa.Column("locked_features", sa.JSON(), nullable=False),
    sa.UniqueConstraint("chat_id", "topic_id", name="uq_chat_topic"),
)

sa.Table(
    "group_stats", metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("chat_id", sa.BigInteger(), _chat_fk(), nullable=False),
    sa.Column("date", sa.Date(), nullable=False),
    sa.Column("messages_count", sa.Integer(), nullable=False),
    sa.Column("joins_count", sa.Integer(), nullable=False),
    sa.Column("leaves_count", sa.Integer(), nullable=False),
    sa.Column("sanctions_count", sa.Integer(), nullable=False),
    sa.UniqueConstraint("chat_id", "date", name="uq_chat_date"),
)

sa.Table(
    "bot_clones", metadata,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("owner_user_id", sa.BigInteger(), nullable=False, index=True),
    sa.Column("bot_id", sa.BigInteger(), nullable=True),
    sa.Column("bot_username", sa.String(64), nullable=False),
    sa.Column("token_encrypted", sa.Text(), nullable=False),
    sa.Column("token_hash", sa.String(64), nullable=False, unique=True, index=True),
    sa.Column("is_active", sa.Boolean(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
)


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind, checkfirst=True)
    legacy.run_all(bind)


def downgrade() -> None:
    # Откат базовой схемы означал бы удаление всех данных. Не делаем этого автоматически.
    pass
