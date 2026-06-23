"""add voice sessions

Revision ID: 0010_voice_sessions
Revises: 0009_rag_user_settings
Create Date: 2026-06-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_voice_sessions"
down_revision: str | None = "0009_rag_user_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voice_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("speechcloud_session_id", sa.String(length=160), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_voice_sessions_user_id", "voice_sessions", ["user_id"])
    op.create_index("ix_voice_sessions_conversation_id", "voice_sessions", ["conversation_id"])
    op.create_index("ix_voice_sessions_token_hash", "voice_sessions", ["token_hash"], unique=True)
    op.create_index("ix_voice_sessions_status", "voice_sessions", ["status"])
    op.create_index("ix_voice_sessions_speechcloud_session_id", "voice_sessions", ["speechcloud_session_id"])
    op.create_index("ix_voice_sessions_expires_at", "voice_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_voice_sessions_expires_at", table_name="voice_sessions")
    op.drop_index("ix_voice_sessions_speechcloud_session_id", table_name="voice_sessions")
    op.drop_index("ix_voice_sessions_status", table_name="voice_sessions")
    op.drop_index("ix_voice_sessions_token_hash", table_name="voice_sessions")
    op.drop_index("ix_voice_sessions_conversation_id", table_name="voice_sessions")
    op.drop_index("ix_voice_sessions_user_id", table_name="voice_sessions")
    op.drop_table("voice_sessions")
