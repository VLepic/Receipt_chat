from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.models.inference import InferenceRoutingSettings
from app.core.config import settings
from app.services.ollama_servers import get_routing_server
from app.schemas.processing import ProcessingOptions

ROLES = ("chat", "embedding", "reranker", "ocr", "structuring")


async def get_or_create_inference_routing(session: AsyncSession) -> InferenceRoutingSettings:
    routing = await session.scalar(
        select(InferenceRoutingSettings).where(InferenceRoutingSettings.id == "default")
    )
    if routing is None:
        await session.execute(insert(InferenceRoutingSettings).values(
            id="default",
            embedding_model=settings.rag_embedding_model,
            reranker_model=settings.rag_reranker_model,
            processing_options=legacy_processing_options().model_dump(),
        ).on_conflict_do_nothing(index_elements=["id"]))
        routing = await session.get(InferenceRoutingSettings, "default")
    return routing


def legacy_processing_options() -> ProcessingOptions:
    return ProcessingOptions(
        ocr_engine=settings.ocr_engine,
        ocr_model=settings.ollama_ocr_model or None,
        ocr_prompt=settings.ollama_ocr_prompt,
        extraction_mode=settings.extraction_mode,
        rag_search_limit=settings.rag_search_limit,
        reranker_candidate_limit=settings.rag_reranker_candidate_limit,
        inference_timeout_seconds=max(10, int(settings.ollama_timeout_seconds)),
    )


def processing_options(routing) -> ProcessingOptions:
    stored = routing.processing_options or {}
    return ProcessingOptions.model_validate(stored) if stored else legacy_processing_options()


async def get_processing_options(session: AsyncSession) -> ProcessingOptions:
    return processing_options(await get_or_create_inference_routing(session))


async def get_role_server(session: AsyncSession, role: str):
    if role not in ROLES:
        raise ValueError(f"Unknown inference role: {role}")
    routing = await get_or_create_inference_routing(session)
    return get_routing_server(routing, getattr(routing, f"{role}_server_id"))
