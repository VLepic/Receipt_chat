import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.inference_routing import get_or_create_inference_routing
from app.services.ollama import OllamaClient
from app.services.ollama_servers import get_ollama_server

logger = logging.getLogger("sp2.rag.reranker")


async def rerank_document_chunks(
    session: AsyncSession,
    query: str,
    chunks: list[dict],
) -> tuple[list[dict], bool]:
    if not chunks:
        return chunks, False

    routing = await get_or_create_inference_routing(session)
    model = routing.reranker_model or settings.rag_reranker_model
    if not model:
        return chunks, False
    if not routing.reranker_server_id:
        return chunks, False

    client = OllamaClient(get_ollama_server(routing.reranker_server_id))
    candidate_limit = max(1, min(settings.rag_reranker_candidate_limit, 50))
    candidates = chunks[:candidate_limit]
    reranked = []
    try:
        for chunk in candidates:
            score = await client.rerank_score(query, str(chunk.get("content") or ""), model)
            reranked.append({**chunk, "reranker_score": score, "reranker_model": model})
    except Exception:
        logger.exception("Reranking failed; using vector order")
        return chunks, False

    reranked.sort(key=lambda chunk: float(chunk["reranker_score"]), reverse=True)
    reranked.extend(chunks[candidate_limit:])
    return reranked, True
