import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_active_user, current_admin_user
from app.core.db import get_async_session
from app.models.user import User
from app.schemas.inference import (
    InferenceConfigurationRead,
    InferenceRoutingRead,
    InferenceRoutingUpdate,
    InferenceServerRead,
)
from app.schemas.processing import ProcessingOptions
from app.schemas.servers import ServerSettingsUpdate
from app.services.server_settings import merge_server_settings, public_server_settings
from app.services.inference_routing import get_or_create_inference_routing, processing_options
from app.services.ollama import OllamaClient
from app.services.ollama_servers import routing_servers, routing_server_records, server_from_record

router = APIRouter(prefix="/inference", tags=["inference"])


@router.put("/processing", response_model=ProcessingOptions)
async def update_processing_options(
    payload: ProcessingOptions,
    _user: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_async_session),
) -> ProcessingOptions:
    routing = await get_or_create_inference_routing(session)
    if payload.ocr_engine == "ollama":
        server = next((item for item in routing_servers(routing) if item.id == routing.ocr_server_id), None)
        snapshots = [await _server_snapshot(server)] if server else []
        _require_server_model("OCR", routing.ocr_server_id, payload.ocr_model, snapshots)
    routing.processing_options = payload.model_dump()
    await session.commit()
    return payload


@router.put("/servers", response_model=InferenceConfigurationRead)
async def update_servers(
    payload: list[ServerSettingsUpdate],
    _user: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_async_session),
) -> InferenceConfigurationRead:
    if len(payload) != 2 or {item.id for item in payload} != {"server_1", "server_2"}:
        raise HTTPException(422, "Nastavení musí obsahovat server_1 a server_2 právě jednou.")
    routing = await get_or_create_inference_routing(session)
    previous = {record["id"]: record for record in routing_server_records(routing)}
    routing.server_configs = [merge_server_settings(item, previous.get(item.id, {})) for item in payload]
    await session.commit()
    return await read_inference_configuration(_user=_user, session=session)


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


async def _record_snapshot(record: dict) -> InferenceServerRead:
    try:
        return await _server_snapshot(server_from_record(record))
    except HTTPException as exc:
        return InferenceServerRead(
            id=record["id"], name=record["name"], reachable=False, models=[], detail=str(exc.detail)
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
        default_model=None,
        snapshots=snapshots,
    )
    routing.reranker_server_id, routing.reranker_model = _normalize_model_route(
        current_server_id=routing.reranker_server_id,
        current_model=routing.reranker_model,
        default_model=None,
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
    records = [record for record in routing_server_records(routing) if record["enabled"]]
    snapshots = await asyncio.gather(*(_record_snapshot(record) for record in records))
    _normalize_routing(routing, snapshots)
    await session.commit()
    return InferenceConfigurationRead(
        servers=list(snapshots),
        routing=_routing_read(routing),
        reranker_enabled=bool(records),
        processing=processing_options(routing),
        server_settings=[public_server_settings(record) for record in routing_server_records(routing)] if _user.is_superuser else [],
    )


@router.put("", response_model=InferenceConfigurationRead)
async def update_inference_configuration(
    payload: InferenceRoutingUpdate,
    _user: User = Depends(current_admin_user),
    session: AsyncSession = Depends(get_async_session),
) -> InferenceConfigurationRead:
    routing = await get_or_create_inference_routing(session)
    servers = routing_servers(routing)
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
            detail=f"Neznámý nebo nenakonfigurovaný inference server: {', '.join(sorted(unknown))}",
        )

    snapshots = await asyncio.gather(*(_server_snapshot(server) for server in servers))
    if payload.embedding_model:
        _require_server_model("Embedding", payload.embedding_server_id, payload.embedding_model, snapshots)
    if payload.reranker_server_id:
        reranker_server = next(server for server in servers if server.id == payload.reranker_server_id)
        if reranker_server.api_type != "ollama":
            raise HTTPException(422, "Reranking vyžaduje Ollama server se samostatným reranker modelem.")
        _require_server_model("Reranking", payload.reranker_server_id, payload.reranker_model, snapshots)
    else:
        payload.reranker_model = None

    options = payload.processing or processing_options(routing)
    if options.ocr_engine == "ollama":
        _require_server_model("OCR", payload.ocr_server_id, options.ocr_model, snapshots)

    routing = await get_or_create_inference_routing(session)
    for field, value in payload.model_dump(exclude={"processing"}).items():
        setattr(routing, field, value)
    if payload.processing is not None:
        routing.processing_options = payload.processing.model_dump()
    await session.commit()
    await session.refresh(routing)
    return InferenceConfigurationRead(
        servers=list(snapshots),
        routing=_routing_read(routing),
        reranker_enabled=bool(servers),
        processing=processing_options(routing),
        server_settings=[public_server_settings(record) for record in routing_server_records(routing)],
    )
