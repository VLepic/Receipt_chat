import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_active_user
from app.core.config import settings
from app.core.db import get_async_session
from app.models.user import User
from app.schemas.inference import (
    InferenceConfigurationRead,
    InferenceRoutingRead,
    InferenceRoutingUpdate,
    InferenceServerRead,
)
from app.services.inference_routing import get_or_create_inference_routing
from app.services.ollama import OllamaClient
from app.services.ollama_servers import configured_ollama_servers

router = APIRouter(prefix="/inference", tags=["inference"])


async def _server_snapshot(server) -> InferenceServerRead:
    client = OllamaClient(server)
    try:
        models = await client.list_models()
        return InferenceServerRead(
            id=server.id,
            name=server.name,
            reachable=True,
            models=[str(item["name"]) for item in models],
        )
    except HTTPException as exc:
        return InferenceServerRead(
            id=server.id,
            name=server.name,
            reachable=False,
            models=[],
            detail=str(exc.detail),
        )
    except Exception:
        return InferenceServerRead(
            id=server.id,
            name=server.name,
            reachable=False,
            models=[],
            detail="Odpověď serveru se nepodařilo načíst",
        )


def _routing_read(routing) -> InferenceRoutingRead:
    return InferenceRoutingRead(
        chat_server_id=routing.chat_server_id,
        embedding_server_id=routing.embedding_server_id,
        embedding_model=routing.embedding_model,
        reranker_server_id=routing.reranker_server_id,
        reranker_model=routing.reranker_model,
        ocr_server_id=routing.ocr_server_id,
        structuring_server_id=routing.structuring_server_id,
    )


def _validated_default_model(server_id: str | None, model: str | None, snapshots) -> str | None:
    if not server_id or not model:
        return None
    server = next((item for item in snapshots if item.id == server_id), None)
    if server is None or not server.reachable:
        return model
    return model if model in server.models else None


def _server_ids(snapshots) -> set[str]:
    return {server.id for server in snapshots}


def _reachable_servers(snapshots):
    return [server for server in snapshots if server.reachable]


def _fallback_server_id(server_id: str | None, snapshots) -> str | None:
    known_ids = _server_ids(snapshots)
    if server_id in known_ids and _server_reachable(server_id, snapshots):
        return server_id
    reachable = _reachable_servers(snapshots)
    if reachable:
        return reachable[0].id
    if server_id in known_ids:
        return server_id
    return snapshots[0].id if snapshots else None


def _server_with_model(model: str | None, snapshots) -> str | None:
    if not model:
        return None
    for server in _reachable_servers(snapshots):
        if model in server.models:
            return server.id
    return None


def _server_reachable(server_id: str | None, snapshots) -> bool:
    server = next((item for item in snapshots if item.id == server_id), None)
    return bool(server and server.reachable)


def _normalize_model_route(
    *,
    current_server_id: str | None,
    current_model: str | None,
    default_model: str | None,
    snapshots,
    optional: bool = False,
) -> tuple[str | None, str | None]:
    candidate_model = current_model or default_model
    if not snapshots:
        return current_server_id, candidate_model

    if candidate_model:
        model_server_id = _server_with_model(candidate_model, snapshots)
        if model_server_id:
            return model_server_id, candidate_model

    fallback_server_id = _fallback_server_id(current_server_id, snapshots)
    if optional and (not candidate_model or current_server_id not in _server_ids(snapshots)):
        return None, None
    if optional and candidate_model and _server_reachable(fallback_server_id, snapshots):
        return None, None
    return fallback_server_id, None if _server_reachable(fallback_server_id, snapshots) else candidate_model


def _normalize_routing(routing, snapshots) -> None:
    routing.chat_server_id = _fallback_server_id(routing.chat_server_id, snapshots) or routing.chat_server_id
    routing.ocr_server_id = _fallback_server_id(routing.ocr_server_id, snapshots) or routing.ocr_server_id
    routing.structuring_server_id = (
        _fallback_server_id(routing.structuring_server_id, snapshots) or routing.structuring_server_id
    )
    routing.embedding_server_id, routing.embedding_model = _normalize_model_route(
        current_server_id=routing.embedding_server_id,
        current_model=routing.embedding_model,
        default_model=settings.rag_embedding_model,
        snapshots=snapshots,
    )
    routing.reranker_server_id, routing.reranker_model = _normalize_model_route(
        current_server_id=routing.reranker_server_id,
        current_model=routing.reranker_model,
        default_model=settings.rag_reranker_model,
        snapshots=snapshots,
        optional=True,
    )


def _require_server_model(role: str, server_id: str, model: str | None, snapshots) -> None:
    server = next((item for item in snapshots if item.id == server_id), None)
    if server is None or not server.reachable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Nelze ověřit model pro roli {role}: server není dostupný.",
        )
    if not model:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Vyberte model pro roli {role}.",
        )
    if model not in server.models:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Model {model} není dostupný na serveru {server.name} pro roli {role}.",
        )


@router.get("", response_model=InferenceConfigurationRead)
async def read_inference_configuration(
    _user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> InferenceConfigurationRead:
    routing = await get_or_create_inference_routing(session)
    servers = configured_ollama_servers()
    snapshots = await asyncio.gather(*(_server_snapshot(server) for server in servers))
    _normalize_routing(routing, snapshots)
    await session.commit()
    return InferenceConfigurationRead(
        servers=list(snapshots),
        routing=_routing_read(routing),
        reranker_enabled=bool(servers),
    )


@router.put("", response_model=InferenceConfigurationRead)
async def update_inference_configuration(
    payload: InferenceRoutingUpdate,
    _user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> InferenceConfigurationRead:
    servers = configured_ollama_servers()
    server_ids = {server.id for server in servers}
    selected = {
        payload.chat_server_id,
        payload.embedding_server_id,
        payload.ocr_server_id,
        payload.structuring_server_id,
    }
    if payload.reranker_server_id:
        selected.add(payload.reranker_server_id)
    unknown = selected - server_ids
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Neznámý nebo nenakonfigurovaný Ollama server: {', '.join(sorted(unknown))}",
        )

    snapshots = await asyncio.gather(*(_server_snapshot(server) for server in servers))
    _require_server_model("Embedding", payload.embedding_server_id, payload.embedding_model, snapshots)
    if payload.reranker_server_id:
        _require_server_model("Reranking", payload.reranker_server_id, payload.reranker_model, snapshots)
    else:
        payload.reranker_model = None

    routing = await get_or_create_inference_routing(session)
    for field, value in payload.model_dump().items():
        setattr(routing, field, value)
    await session.commit()
    await session.refresh(routing)
    return InferenceConfigurationRead(
        servers=list(snapshots),
        routing=_routing_read(routing),
        reranker_enabled=bool(servers),
    )
