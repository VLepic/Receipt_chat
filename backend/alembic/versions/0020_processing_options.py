"""Persist document processing and retrieval configuration."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0020_processing_options"
down_revision = "0019_remove_voice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inference_routing_settings", sa.Column("server_configs", postgresql.JSONB(), nullable=True))
    op.add_column(
        "inference_routing_settings",
        sa.Column("processing_options", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("inference_routing_settings", "processing_options")
    op.drop_column("inference_routing_settings", "server_configs")
