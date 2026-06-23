"""add inference role models"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_inference_models"
down_revision: str | None = "0016_reranker_best_band"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("inference_routing_settings")
    }
    if "embedding_model" not in columns:
        op.add_column(
            "inference_routing_settings",
            sa.Column("embedding_model", sa.String(length=160), nullable=True),
        )
    if "reranker_model" not in columns:
        op.add_column(
            "inference_routing_settings",
            sa.Column("reranker_model", sa.String(length=160), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("inference_routing_settings", "reranker_model")
    op.drop_column("inference_routing_settings", "embedding_model")
