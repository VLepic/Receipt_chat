"""add default chat model setting

Revision ID: 0011_default_chat_model
Revises: 0010_voice_sessions
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_default_chat_model"
down_revision: str | None = "0010_voice_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("default_chat_model", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "default_chat_model")
