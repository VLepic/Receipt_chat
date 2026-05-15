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
from app.services.vector_store import build_chat_context, search_document_chunks

router = APIRouter(prefix="/chat", tags=["chat"])


def _message_sources(message: Message) -> list[ChatSource]:
    sources = (message.metadata_json or {}).get("sources", [])
    return [ChatSource(**source) for source in sources if isinstance(source, dict)]


def _message_read(message: Message) -> MessageRead:
    return MessageRead(
        id=message.id,
        role=message.role,
        content=message.content,
        model=message.model,
        created_at=message.created_at,
        sources=_message_sources(message),
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
    messages = [{"role": message.role, "content": message.content} for message in conversation.messages]
    rag_chunks = await search_document_chunks(session, user.id, payload.content)
    rag_context = build_chat_context(rag_chunks)
    if rag_context:
        messages.insert(
            0,
            {
                "role": "system",
                "content": (
                    f"{rag_context}\n\n"
                    "Odpovidej jen podle zdroju, ktere skutecne souvisi s dotazem; nesouvisejici doklady ignoruj. "
                    "Syrova UUID ani document_id nikdy neopisuj do textu odpovedi, pokud se na ne uzivatel primo nepta. "
                    "Backend relevantni doklady zobrazi jako klikatelne zdroje pod odpovedi."
                ),
            },
        )
    messages.append({"role": MessageRole.user, "content": payload.content})

    selected_model = payload.model or settings.ollama_model
    client = OllamaClient()
    assistant_text = await client.chat(messages, model=selected_model)
    assistant_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.assistant,
        content=assistant_text,
        model=selected_model,
        metadata_json={"sources": _sources_from_chunks(rag_chunks, user_settings)},
    )
    session.add(assistant_message)
    await session.commit()

    conversation = await _get_owned_conversation(conversation_id, user, session)
    return ChatResponse(
        conversation=_conversation_detail(conversation),
        assistant_message=_message_read(assistant_message),
    )
