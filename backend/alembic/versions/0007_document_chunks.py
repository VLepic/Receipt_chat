"""add document chunks for rag

Revision ID: 0007_document_chunks
Revises: 0006_document_files
Create Date: 2026-05-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_document_chunks"
down_revision: str | None = "0006_document_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE document_chunks (
            id uuid PRIMARY KEY,
            document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
            chunk_index integer NOT NULL DEFAULT 0,
            content text NOT NULL,
            metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            embedding vector NOT NULL,
            embedding_model varchar(120) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX uq_document_chunks_document_index ON document_chunks(document_id, chunk_index)")
    op.execute("CREATE INDEX ix_document_chunks_user_id ON document_chunks(user_id)")
    op.execute("CREATE INDEX ix_document_chunks_document_id ON document_chunks(document_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_document_id")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_user_id")
    op.execute("DROP INDEX IF EXISTS uq_document_chunks_document_index")
    op.execute("DROP TABLE IF EXISTS document_chunks")
