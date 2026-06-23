"""add inference routing settings

Revision ID: 0015_inference_routing
Revises: 0014_repair_message_sort_order
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_inference_routing"
down_revision: str | None = "0014_repair_message_sort_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("inference_routing_settings"):
        op.create_table(
            "inference_routing_settings",
            sa.Column("id", sa.String(length=40), nullable=False),
            sa.Column("chat_server_id", sa.String(length=40), nullable=False),
            sa.Column("embedding_server_id", sa.String(length=40), nullable=False),
            sa.Column("reranker_server_id", sa.String(length=40), nullable=True),
            sa.Column("ocr_server_id", sa.String(length=40), nullable=False),
            sa.Column("structuring_server_id", sa.String(length=40), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    op.execute(
        """
        INSERT INTO inference_routing_settings
            (id, chat_server_id, embedding_server_id, reranker_server_id, ocr_server_id, structuring_server_id)
        VALUES ('default', 'server_1', 'server_1', NULL, 'server_1', 'server_1')
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("inference_routing_settings")
