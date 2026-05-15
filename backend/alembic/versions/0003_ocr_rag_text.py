"""add ocr rag text

Revision ID: 0003_ocr_rag_text
Revises: 0002_ocr_results
Create Date: 2026-05-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_ocr_rag_text"
down_revision: str | None = "0002_ocr_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ocr_results", sa.Column("rag_text", sa.Text(), nullable=False, server_default=""))
    op.add_column(
        "ocr_results",
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.alter_column("ocr_results", "rag_text", server_default=None)
    op.alter_column("ocr_results", "metadata_json", server_default=None)


def downgrade() -> None:
    op.drop_column("ocr_results", "metadata_json")
    op.drop_column("ocr_results", "rag_text")
