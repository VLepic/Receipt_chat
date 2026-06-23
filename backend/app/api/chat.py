import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
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
from app.services.chat_agent import generate_chat_agent_response
from app.services.inference_routing import get_role_server
from app.services.ollama import OllamaClient

router = APIRouter(prefix="/chat", tags=["chat"])


def message_sources(message: Message) -> list[ChatSource]:
    sources = (message.metadata_json or {}).get("sources", [])
    return [ChatSource(**source) for source in sources if isinstance(source, dict)]


def message_retrieval(message: Message) -> dict | None:
    retrieval = (message.metadata_json or {}).get("retrieval")
    return retrieval if isinstance(retrieval, dict) else None


def message_read(message: Message) -> MessageRead:
    return MessageRead(
        id=message.id,
        role=message.role,
        content=message.content,
        model=message.model,
        created_at=message.created_at,
        sources=message_sources(message),
        retrieval=message_retrieval(message),
    )


def conversation_detail(conversation: Conversation) -> ConversationDetail:
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[message_read(message) for message in conversation.messages],
    )


async def get_user_settings(user_id: uuid.UUID, session: AsyncSession) -> UserSettings:
    result = await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    user_settings = result.scalar_one_or_none()
    if user_settings is not None:
        return user_settings

    user_settings = UserSettings(user_id=user_id)
    session.add(user_settings)
    await session.flush()
    return user_settings


async def get_owned_conversation(
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


async def append_chat_message_pair(
    *,
    session: AsyncSession,
    conversation: Conversation,
    user: User,
    content: str,
    model: str | None = None,
    response_mode: str = "chat",
) -> tuple[Conversation, Message, Message]:
    user_settings = await get_user_settings(user.id, session)
    selected_model = model or user_settings.default_chat_model or settings.ollama_model
    chat_client = OllamaClient(await get_role_server(session, "chat"))

    await session.execute(select(Conversation.id).where(Conversation.id == conversation.id).with_for_update())
    history_result = await session.execute(
        select(Message.role, Message.content, Message.metadata_json)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.sort_order, Message.created_at, Message.id)
    )
    history = []
    for row in history_result:
        retrieval = (row.metadata_json or {}).get("retrieval")
        unsupported_document_answer = (
            row.role == MessageRole.assistant
            and isinstance(retrieval, dict)
            and retrieval.get("mode") != "none"
            and int(retrieval.get("source_count") or 0) == 0
        )
        if not unsupported_document_answer:
            history.append({"role": row.role, "content": row.content})
    sort_order_result = await session.execute(
        select(func.coalesce(func.max(Message.sort_order), -1) + 1).where(
            Message.conversation_id == conversation.id
        )
    )
    next_sort_order = int(sort_order_result.scalar_one())

    user_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.user,
        content=content,
        sort_order=next_sort_order,
    )
    session.add(user_message)
    await session.flush()

    agent_result = await generate_chat_agent_response(
        session=session,
        user_id=user.id,
        user_settings=user_settings,
        history=history,
        content=content,
        model=selected_model,
        conversation_id=conversation.id,
        client=chat_client,
        response_mode=response_mode,
    )
    assistant_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.assistant,
        content=agent_result.content,
        model=agent_result.model,
        metadata_json={"sources": agent_result.sources, "retrieval": agent_result.retrieval},
        sort_order=next_sort_order + 1,
    )
    session.add(assistant_message)
    await session.commit()
    await session.refresh(assistant_message)

    refreshed = await session.execute(
        select(Conversation)
        .where(Conversation.id == conversation.id, Conversation.user_id == user.id)
        .options(selectinload(Conversation.messages))
        .execution_options(populate_existing=True)
    )
    return refreshed.scalar_one(), user_message, assistant_message


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
    session: AsyncSession = Depends(get_async_session),
) -> list[dict[str, str | bool]]:
    return await OllamaClient(await get_role_server(session, "chat")).list_models()


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
    conversation = await get_owned_conversation(conversation_id, user, session)
    return conversation_detail(conversation)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    conversation = await get_owned_conversation(conversation_id, user, session)
    await session.delete(conversation)
    await session.commit()


@router.post("/conversations/{conversation_id}/messages", response_model=ChatResponse)
async def send_message(
    conversation_id: uuid.UUID,
    payload: ChatRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> ChatResponse:
    conversation = await get_owned_conversation(conversation_id, user, session)
    updated_conversation, _user_message, assistant_message = await append_chat_message_pair(
        session=session,
        conversation=conversation,
        user=user,
        content=payload.content,
        model=payload.model,
    )
    return ChatResponse(
        conversation=conversation_detail(updated_conversation),
        assistant_message=message_read(assistant_message),
    )
