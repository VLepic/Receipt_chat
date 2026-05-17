import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import current_active_user
from app.core.config import settings
from app.core.db import get_async_session
from app.models.conversation import Conversation, Message, MessageRole
from app.models.settings import UserSettings
from app.models.user import User
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatSource,
    ConversationCreate,
    ConversationDetail,
    ConversationRead,
    MessageRead,
    OllamaModelRead,
)
from app.services.ollama import OllamaClient
from app.services.vector_store import build_chat_context, search_document_chunks, search_document_structured

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger("sp2.chat.agent")


def _log_preview(value: str, limit: int = 500) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else f"{normalized[:limit]}..."


def _message_sources(message: Message) -> list[ChatSource]:
    sources = (message.metadata_json or {}).get("sources", [])
    return [ChatSource(**source) for source in sources if isinstance(source, dict)]


def _message_retrieval(message: Message) -> dict | None:
    retrieval = (message.metadata_json or {}).get("retrieval")
    return retrieval if isinstance(retrieval, dict) else None


def _message_read(message: Message) -> MessageRead:
    return MessageRead(
        id=message.id,
        role=message.role,
        content=message.content,
        model=message.model,
        created_at=message.created_at,
        sources=_message_sources(message),
        retrieval=_message_retrieval(message),
    )


def _conversation_detail(conversation: Conversation) -> ConversationDetail:
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[_message_read(message) for message in conversation.messages],
    )


async def _get_user_settings(user_id: uuid.UUID, session: AsyncSession) -> UserSettings:
    result = await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    user_settings = result.scalar_one_or_none()
    if user_settings is not None:
        return user_settings

    user_settings = UserSettings(user_id=user_id)
    session.add(user_settings)
    await session.flush()
    return user_settings


def _sources_from_chunks(chunks: list[dict], user_settings: UserSettings) -> list[dict[str, object]]:
    best_distance = next(
        (float(chunk["distance"]) for chunk in chunks if chunk.get("distance") is not None),
        None,
    )
    max_sources = max(1, min(user_settings.rag_top_n or 2, 10))
    best_band = max(0.0, float(user_settings.rag_best_band or 0.0))
    use_best_band = user_settings.rag_source_strategy == "best_band"
    sources = []
    seen_document_ids = set()
    for chunk in chunks:
        document_id = str(chunk.get("document_id") or "")
        if not document_id or document_id in seen_document_ids:
            continue
        distance = chunk.get("distance")
        if use_best_band and best_distance is not None and distance is not None and float(distance) > best_distance + best_band:
            continue
        seen_document_ids.add(document_id)
        sources.append(
            {
                "document_id": document_id,
                "title": chunk.get("summary") or chunk.get("filename") or "Doklad",
                "filename": chunk.get("filename"),
                "distance": distance,
            }
        )
        if len(sources) >= max_sources:
            break
    return sources


def _merge_chunks(*chunk_groups: list[dict]) -> list[dict]:
    merged = []
    seen = set()
    for chunks in chunk_groups:
        for chunk in chunks:
            document_id = str(chunk.get("document_id") or "")
            if not document_id or document_id in seen:
                continue
            seen.add(document_id)
            merged.append(chunk)
    return merged


def _retrieval_metadata(used_rag: bool, used_search: bool, source_count: int) -> dict[str, object]:
    if used_rag and used_search:
        mode = "hybrid"
    elif used_rag:
        mode = "rag"
    elif used_search:
        mode = "search"
    else:
        mode = "none"
    return {
        "mode": mode,
        "used_rag": used_rag,
        "used_search": used_search,
        "source_count": source_count,
    }


def _parse_agent_command(text: str) -> dict | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`").strip()
        if candidate.startswith("json"):
            candidate = candidate[4:].strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _agent_decision_messages(history: list[dict], content: str) -> list[dict]:
    recent_history = history[-6:]
    return [
        {
            "role": "system",
            "content": (
                "Jsi interní rozhodovací vrstva chatu nad osobními doklady. "
                "Vrať pouze validní JSON bez markdownu. "
                "Pokud lze odpovědět bez dokladů, vrať {\"action\":\"answer\",\"content\":\"...\"}. "
                "Pokud dotaz vyžaduje informace z dokladů, vrať "
                "{\"action\":\"search_documents\",\"search\":{\"rag_queries\":[\"...\"],"
                "\"structured\":{\"merchant\":null,\"item\":null,\"date\":{\"mode\":null,\"value\":null,\"value_to\":null},"
                "\"amount\":{\"mode\":null,\"value\":null,\"value_to\":null}}}}. "
                "Dotazy na nakupy, uctenky, faktury, ceny, polozky, obchod, datum nakupu, provozovnu, adresu nebo doklad "
                "vzdy vyzaduji search_documents, i kdyz se odpoved zda byt zrejma z historie chatu. "
                "Konkretní fakta z dokladu nikdy neodpovidej pouze z historie nebo pameti; nejdriv si vyzadej hledani, aby backend mohl pripojit zdroje. "
                "U navazujících dotazů použij historii pro vytvoření samostatných hledacích textů. "
                "Nevymýšlej údaje z dokladů bez výsledků hledání."
            ),
        },
        *recent_history,
        {"role": "user", "content": content},
    ]


def _rag_queries_from_command(command: dict, fallback: str) -> list[str]:
    search = command.get("search") if isinstance(command.get("search"), dict) else {}
    raw_queries = search.get("rag_queries") or search.get("queries") or []
    if isinstance(raw_queries, str):
        raw_queries = [raw_queries]
    queries = [query.strip() for query in raw_queries if isinstance(query, str) and query.strip()]
    return queries[:3] or [fallback]


def _structured_query_from_command(command: dict) -> str:
    search = command.get("search") if isinstance(command.get("search"), dict) else {}
    structured = search.get("structured") if isinstance(search.get("structured"), dict) else {}
    explicit = search.get("structured_query")
    parts = [explicit.strip()] if isinstance(explicit, str) and explicit.strip() else []
    for key in ("merchant", "item", "document_type", "invoice_number", "variable_symbol"):
        value = structured.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    for key in ("date", "amount"):
        nested = structured.get(key)
        if isinstance(nested, dict):
            for nested_key in ("value", "value_to"):
                value = nested.get(nested_key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
                elif isinstance(value, int | float):
                    parts.append(str(value))
    return " ".join(dict.fromkeys(parts))


async def _run_document_retrieval(
    session: AsyncSession,
    user_id: uuid.UUID,
    command: dict | None,
    fallback_query: str,
) -> tuple[list[dict], dict[str, object]]:
    if command is None:
        rag_chunks = await search_document_chunks(session, user_id, fallback_query)
        return rag_chunks, _retrieval_metadata(used_rag=True, used_search=False, source_count=0)

    rag_queries = _rag_queries_from_command(command, fallback_query)
    structured_query = _structured_query_from_command(command)
    rag_results = []
    for query in rag_queries:
        rag_results.extend(await search_document_chunks(session, user_id, query))
    structured_results = await search_document_structured(session, user_id, structured_query) if structured_query else []
    chunks = _merge_chunks(structured_results, rag_results)
    return chunks, _retrieval_metadata(
        used_rag=bool(rag_queries),
        used_search=bool(structured_query),
        source_count=0,
    )


def _final_messages(history: list[dict], content: str, rag_context: str, retrieval: dict[str, object]) -> list[dict]:
    system_content = (
        "Odpovidej přirozeně česky. "
        "Syrova UUID ani document_id nikdy neopisuj do textu odpovedi, pokud se na ne uzivatel primo nepta. "
        "Backend relevantni doklady zobrazi jako klikatelne zdroje pod odpovedi."
    )
    if rag_context:
        system_content = (
            f"{rag_context}\n\n"
            "Odpovidej jen podle zdroju, ktere skutecne souvisi s dotazem; nesouvisejici doklady ignoruj. "
            + system_content
        )
    elif retrieval.get("mode") != "none":
        system_content = (
            "Vyhledavani v dokladech nevratilo zadny spolehlivy kontext. "
            "Pokud se uzivatel pta na doklady, rekni, ze v ulozenych dokladech nebyl nalezen relevantni zaznam. "
            + system_content
        )
    return [{"role": "system", "content": system_content}, *history, {"role": "user", "content": content}]


async def _get_owned_conversation(
    conversation_id: uuid.UUID,
    user: User,
    session: AsyncSession,
) -> Conversation:
    result = await session.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.user_id == user.id)
        .options(selectinload(Conversation.messages))
        .execution_options(populate_existing=True)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


@router.get("/conversations", response_model=list[ConversationRead])
async def list_conversations(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[Conversation]:
    result = await session.execute(
        select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc())
    )
    return list(result.scalars().all())


@router.get("/models", response_model=list[OllamaModelRead])
async def list_models(
    user: User = Depends(current_active_user),
) -> list[dict[str, str | bool]]:
    return await OllamaClient().list_models()


@router.post("/conversations", response_model=ConversationDetail, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> ConversationDetail:
    conversation = Conversation(user_id=user.id, title=payload.title)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[],
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> ConversationDetail:
    conversation = await _get_owned_conversation(conversation_id, user, session)
    return _conversation_detail(conversation)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    conversation = await _get_owned_conversation(conversation_id, user, session)
    await session.delete(conversation)
    await session.commit()


@router.post("/conversations/{conversation_id}/messages", response_model=ChatResponse)
async def send_message(
    conversation_id: uuid.UUID,
    payload: ChatRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> ChatResponse:
    conversation = await _get_owned_conversation(conversation_id, user, session)

    user_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.user,
        content=payload.content,
    )
    session.add(user_message)
    await session.flush()

    user_settings = await _get_user_settings(user.id, session)
    history = [{"role": message.role, "content": message.content} for message in conversation.messages]
    selected_model = payload.model or settings.ollama_model
    client = OllamaClient()

    logger.info(
        "agent decision start conversation_id=%s user_id=%s model=%s history_messages=%d user_message=%r",
        conversation.id,
        user.id,
        selected_model,
        len(history),
        _log_preview(payload.content, 240),
    )
    decision_text = await client.chat(_agent_decision_messages(history, payload.content), model=selected_model)
    logger.info(
        "agent decision raw conversation_id=%s response=%r",
        conversation.id,
        _log_preview(decision_text),
    )
    decision = _parse_agent_command(decision_text)
    rag_chunks: list[dict] = []
    retrieval = _retrieval_metadata(False, False, 0)

    if decision and decision.get("action") == "answer" and isinstance(decision.get("content"), str):
        logger.info(
            "agent decision parsed conversation_id=%s action=answer",
            conversation.id,
        )
        assistant_text = decision["content"]
        logger.info(
            "agent direct answer conversation_id=%s response=%r",
            conversation.id,
            _log_preview(assistant_text),
        )
    else:
        search_command = decision if decision and decision.get("action") == "search_documents" else None
        if search_command:
            rag_queries_for_log = _rag_queries_from_command(search_command, payload.content)
            structured_query_for_log = _structured_query_from_command(search_command)
            logger.info(
                "agent decision parsed conversation_id=%s action=search_documents rag_queries=%s structured_query=%r",
                conversation.id,
                rag_queries_for_log,
                structured_query_for_log,
            )
        else:
            logger.info(
                "agent decision fallback conversation_id=%s reason=invalid_or_missing_json fallback_query=%r",
                conversation.id,
                _log_preview(payload.content, 240),
            )
        rag_chunks, retrieval = await _run_document_retrieval(session, user.id, search_command, payload.content)
        sources = _sources_from_chunks(rag_chunks, user_settings)
        retrieval["source_count"] = len(sources)
        logger.info(
            "agent retrieval finished conversation_id=%s mode=%s used_rag=%s used_search=%s chunks=%d sources=%d",
            conversation.id,
            retrieval["mode"],
            retrieval["used_rag"],
            retrieval["used_search"],
            len(rag_chunks),
            len(sources),
        )
        rag_context = build_chat_context(rag_chunks)
        assistant_text = await client.chat(_final_messages(history, payload.content, rag_context, retrieval), model=selected_model)
        logger.info(
            "agent final answer conversation_id=%s response=%r",
            conversation.id,
            _log_preview(assistant_text),
        )
    
    if not rag_chunks:
        sources = []
    else:
        sources = _sources_from_chunks(rag_chunks, user_settings)
        retrieval["source_count"] = len(sources)
    assistant_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.assistant,
        content=assistant_text,
        model=selected_model,
        metadata_json={"sources": sources, "retrieval": retrieval},
    )
    session.add(assistant_message)
    await session.commit()

    conversation = await _get_owned_conversation(conversation_id, user, session)
    return ChatResponse(
        conversation=_conversation_detail(conversation),
        assistant_message=_message_read(assistant_message),
    )
