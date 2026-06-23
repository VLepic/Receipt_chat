"""add deterministic message ordering

Revision ID: 0013_message_sort_order
Revises: 0012_tts_voice
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_message_sort_order"
down_revision: str | None = "0012_tts_voice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("sort_order", sa.Integer(), nullable=True))
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY conversation_id
                    ORDER BY created_at, id
                ) - 1 AS sort_order
            FROM messages
        )
        UPDATE messages AS message
        SET sort_order = ranked.sort_order
        FROM ranked
        WHERE message.id = ranked.id
        """
    )
    op.alter_column("messages", "sort_order", nullable=False)
    op.create_unique_constraint(
        "uq_messages_conversation_sort_order",
        "messages",
        ["conversation_id", "sort_order"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_messages_conversation_sort_order", "messages", type_="unique")
    op.drop_column("messages", "sort_order")
