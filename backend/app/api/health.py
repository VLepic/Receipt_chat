from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_async_session
from app.services.inference_routing import get_role_server

from app.core.config import settings
from app.services.ollama import OllamaClient

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@router.get("/health/ollama")
async def ollama_health(session: AsyncSession = Depends(get_async_session)) -> dict[str, str | bool]:
    client = OllamaClient(await get_role_server(session, "chat"))
    return await client.health()

