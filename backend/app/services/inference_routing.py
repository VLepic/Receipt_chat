from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inference import InferenceRoutingSettings
from app.core.config import settings
from app.services.ollama_servers import get_ollama_server

ROLES = ("chat", "embedding", "reranker", "ocr", "structuring")


async def get_or_create_inference_routing(session: AsyncSession) -> InferenceRoutingSettings:
    routing = await session.scalar(
        select(InferenceRoutingSettings).where(InferenceRoutingSettings.id == "default")
    )
    if routing is None:
        routing = InferenceRoutingSettings(
            id="default",
            embedding_model=settings.rag_embedding_model,
            reranker_model=settings.rag_reranker_model,
        )
        session.add(routing)
        await session.flush()
    return routing


async def get_role_server(session: AsyncSession, role: str):
    if role not in ROLES:
        raise ValueError(f"Unknown inference role: {role}")
    routing = await get_or_create_inference_routing(session)
    return get_ollama_server(getattr(routing, f"{role}_server_id"))
