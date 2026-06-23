"""add reranker best band"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_reranker_best_band"
down_revision: str | None = "0015_inference_routing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("user_settings")}
    if "rag_reranker_best_band" not in columns:
        op.add_column(
            "user_settings",
            sa.Column("rag_reranker_best_band", sa.Float(), nullable=False, server_default="0.10"),
        )


def downgrade() -> None:
    op.drop_column("user_settings", "rag_reranker_best_band")
