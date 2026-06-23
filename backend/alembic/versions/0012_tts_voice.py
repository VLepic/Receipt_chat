"""add TTS voice setting

Revision ID: 0012_tts_voice
Revises: 0011_default_chat_model
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_tts_voice"
down_revision: str | None = "0011_default_chat_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("tts_voice", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "tts_voice")
