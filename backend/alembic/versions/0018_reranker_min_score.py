"""add reranker minimum score"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_reranker_min_score"
down_revision: str | None = "0017_inference_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("user_settings")}
    if "rag_reranker_min_score" not in columns:
        op.add_column(
            "user_settings",
            sa.Column("rag_reranker_min_score", sa.Float(), nullable=False, server_default="0.50"),
        )


def downgrade() -> None:
    op.drop_column("user_settings", "rag_reranker_min_score")
