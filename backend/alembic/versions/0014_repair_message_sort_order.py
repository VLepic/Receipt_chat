"""repair historical message ordering

Revision ID: 0014_repair_message_sort_order
Revises: 0013_message_sort_order
Create Date: 2026-06-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014_repair_message_sort_order"
down_revision: str | None = "0013_message_sort_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_messages_conversation_sort_order", "messages", type_="unique")
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY conversation_id
                    ORDER BY
                        created_at,
                        CASE role
                            WHEN 'system' THEN 0
                            WHEN 'user' THEN 1
                            WHEN 'assistant' THEN 2
                            ELSE 3
                        END,
                        id
                ) - 1 AS sort_order
            FROM messages
        )
        UPDATE messages AS message
        SET sort_order = ranked.sort_order
        FROM ranked
        WHERE message.id = ranked.id
        """
    )
    op.create_unique_constraint(
        "uq_messages_conversation_sort_order",
        "messages",
        ["conversation_id", "sort_order"],
    )


def downgrade() -> None:
    pass
