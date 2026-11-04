"""chat_settings.data: JSON -> JSONB (issue #13).

JSONB хранится в разобранном виде: быстрее читается, поддерживает индексы и операторы
(@>, ?, ->>) для выборок по настройкам.

Revision ID: 0002_chat_settings_jsonb
Revises: 0001_baseline
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_chat_settings_jsonb"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "chat_settings", "data",
        type_=postgresql.JSONB(), existing_type=sa.JSON(), postgresql_using="data::jsonb",
    )


def downgrade() -> None:
    op.alter_column(
        "chat_settings", "data",
        type_=sa.JSON(), existing_type=postgresql.JSONB(), postgresql_using="data::json",
    )
