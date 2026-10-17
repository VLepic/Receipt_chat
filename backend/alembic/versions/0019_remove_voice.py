"""Remove voice sessions and the TTS preference."""

from alembic import op
import sqlalchemy as sa

revision = "0019_remove_voice"
down_revision = "0018_reranker_min_score"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("voice_sessions")
    op.drop_column("user_settings", "tts_voice")


def downgrade() -> None:
    op.add_column("user_settings", sa.Column("tts_voice", sa.String(120), nullable=True))
    op.create_table(
        "voice_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("speechcloud_session_id", sa.String(160), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("user_id", "conversation_id", "token_hash", "status", "speechcloud_session_id", "expires_at"):
        op.create_index(f"ix_voice_sessions_{column}", "voice_sessions", [column], unique=column == "token_hash")
