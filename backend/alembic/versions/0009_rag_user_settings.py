"""add rag user settings

Revision ID: 0009_rag_user_settings
Revises: 0008_message_metadata
Create Date: 2026-05-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_rag_user_settings"
down_revision: str | None = "0008_message_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("rag_source_strategy", sa.String(length=40), nullable=False, server_default="best_band"),
    )
    op.add_column(
        "user_settings",
        sa.Column("rag_best_band", sa.Float(), nullable=False, server_default="0.08"),
    )
    op.add_column(
        "user_settings",
        sa.Column("rag_top_n", sa.Integer(), nullable=False, server_default="2"),
    )
    op.alter_column("user_settings", "rag_source_strategy", server_default=None)
    op.alter_column("user_settings", "rag_best_band", server_default=None)
    op.alter_column("user_settings", "rag_top_n", server_default=None)


def downgrade() -> None:
    op.drop_column("user_settings", "rag_top_n")
    op.drop_column("user_settings", "rag_best_band")
    op.drop_column("user_settings", "rag_source_strategy")
