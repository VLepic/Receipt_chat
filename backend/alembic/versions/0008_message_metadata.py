"""add message metadata

Revision ID: 0008_message_metadata
Revises: 0007_document_chunks
Create Date: 2026-05-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_message_metadata"
down_revision: str | None = "0007_document_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("messages", "metadata_json", server_default=None)


def downgrade() -> None:
    op.drop_column("messages", "metadata_json")
