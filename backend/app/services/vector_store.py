import json
import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document
from app.services.ollama import OllamaClient

logger = logging.getLogger(__name__)


class RetrievedChunk(dict):
    pass


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


def _compact_metadata(extraction: dict) -> dict:
    merchant = extraction.get("merchant") or {}
    payment = extraction.get("payment") or {}
    total = payment.get("total") or {}
    return {
        "document_type": extraction.get("document_type"),
        "issue_date": extraction.get("issue_date"),
        "merchant": merchant.get("name"),
        "total": total.get("raw") or total.get("amount"),
        "summary": extraction.get("summary"),
    }


async def _document_chunks_table_exists(session: AsyncSession) -> bool:
    result = await session.execute(text("SELECT to_regclass('public.document_chunks') IS NOT NULL"))
    return bool(result.scalar_one())


async def delete_document_chunks(session: AsyncSession, document_id: uuid.UUID) -> None:
    if not settings.rag_embedding_model:
        return
    if not await _document_chunks_table_exists(session):
        return
    await session.execute(text("DELETE FROM document_chunks WHERE document_id = :document_id"), {"document_id": document_id})


async def index_document_rag_text(
    session: AsyncSession,
    document: Document,
    rag_text: str,
    extraction: dict,
    client: OllamaClient | None = None,
) -> bool:
    if not settings.rag_embedding_model or not rag_text.strip():
        return False

    try:
        if not await _document_chunks_table_exists(session):
            return False
        embedding_client = client or OllamaClient()
        embedding = await embedding_client.embed(rag_text, model=settings.rag_embedding_model)
        if not embedding:
            return False

        await delete_document_chunks(session, document.id)
        await session.execute(
            text(
                """
                INSERT INTO document_chunks (
                    id, document_id, user_id, chunk_index, content, metadata_json, embedding, embedding_model
                )
                VALUES (
                    :id, :document_id, :user_id, 0, :content,
                    CAST(:metadata_json AS jsonb), CAST(:embedding AS vector), :embedding_model
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "document_id": document.id,
                "user_id": document.user_id,
                "content": rag_text,
                "metadata_json": json.dumps(_compact_metadata(extraction), ensure_ascii=False),
                "embedding": _vector_literal(embedding),
                "embedding_model": settings.rag_embedding_model,
            },
        )
        return True
    except Exception:
        logger.exception("Document RAG indexing failed for document %s", document.id)
        return False


async def search_document_chunks(
    session: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    limit: int | None = None,
    client: OllamaClient | None = None,
) -> list[RetrievedChunk]:
    if not settings.rag_embedding_model or not query.strip():
        return []

    try:
        if not await _document_chunks_table_exists(session):
            return []
        embedding_client = client or OllamaClient()
        embedding = await embedding_client.embed(query, model=settings.rag_embedding_model)
        if not embedding:
            return []

        result = await session.execute(
            text(
                """
                SELECT
                    dc.document_id::text AS document_id,
                    dc.chunk_index,
                    dc.content,
                    dc.metadata_json,
                    dc.embedding_model,
                    dc.embedding <=> CAST(:embedding AS vector) AS distance,
                    d.filename,
                    de.summary
                FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                LEFT JOIN document_extractions de ON de.document_id = dc.document_id
                WHERE dc.user_id = :user_id
                ORDER BY dc.embedding <=> CAST(:embedding AS vector)
                LIMIT :limit
                """
            ),
            {
                "user_id": user_id,
                "embedding": _vector_literal(embedding),
                "limit": limit or settings.rag_search_limit,
            },
        )
    except Exception:
        logger.exception("Document RAG search failed for user %s", user_id)
        return []

    return [
        RetrievedChunk(
            document_id=row.document_id,
            chunk_index=row.chunk_index,
            content=row.content,
            metadata_json=row.metadata_json,
            embedding_model=row.embedding_model,
            distance=float(row.distance),
            filename=row.filename,
            summary=row.summary,
        )
        for row in result
    ]


async def search_document_structured(
    session: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    limit: int | None = None,
) -> list[RetrievedChunk]:
    terms = [term.strip() for term in query.split() if len(term.strip()) > 1][:8]
    if not terms:
        return []

    where_terms = " AND ".join(f"de.structured_json::text ILIKE :term_{index}" for index in range(len(terms)))
    params = {
        "user_id": user_id,
        "limit": limit or settings.rag_search_limit,
        **{f"term_{index}": f"%{term}%" for index, term in enumerate(terms)},
    }

    try:
        result = await session.execute(
            text(
                f"""
                SELECT
                    de.document_id::text AS document_id,
                    0 AS chunk_index,
                    COALESCE(o.rag_text, de.summary, de.structured_json::text) AS content,
                    jsonb_build_object(
                        'document_type', de.structured_json->>'document_type',
                        'issue_date', de.structured_json->>'issue_date',
                        'summary', de.summary
                    ) AS metadata_json,
                    'structured-json' AS embedding_model,
                    0.0 AS distance,
                    d.filename,
                    de.summary
                FROM document_extractions de
                JOIN documents d ON d.id = de.document_id
                LEFT JOIN ocr_results o ON o.document_id = de.document_id
                WHERE de.user_id = :user_id
                  AND {where_terms}
                ORDER BY de.updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
    except Exception:
        logger.exception("Document structured search failed for user %s", user_id)
        return []

    return [
        RetrievedChunk(
            document_id=row.document_id,
            chunk_index=row.chunk_index,
            content=row.content,
            metadata_json=row.metadata_json,
            embedding_model=row.embedding_model,
            distance=float(row.distance),
            filename=row.filename,
            summary=row.summary,
        )
        for row in result
    ]


def build_chat_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return ""

    sections = [
        "Relevantni doklady z interniho vyhledavani. Pouzij je jako kontext, pokud souvisi s dotazem. "
        "Kdyz odpovidas podle dokladu, zmin nazev nebo souhrn dokladu. Document_id neopisuj do odpovedi."
    ]
    for index, chunk in enumerate(chunks, start=1):
        title = chunk.get("summary") or chunk.get("filename") or chunk.get("document_id")
        sections.append(
            "\n".join(
                [
                    f"[{index}] {title}",
                    f"document_id: {chunk.get('document_id')}",
                    f"distance: {chunk.get('distance'):.4f}",
                    str(chunk.get("content") or ""),
                ]
            )
        )
    return "\n\n".join(sections)
