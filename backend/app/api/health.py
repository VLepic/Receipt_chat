from fastapi import APIRouter

from app.core.config import settings
from app.services.ollama import OllamaClient

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@router.get("/health/ollama")
async def ollama_health() -> dict[str, str | bool]:
    client = OllamaClient()
    return await client.health()

