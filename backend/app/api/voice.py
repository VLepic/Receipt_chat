import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import current_active_user
from app.api.chat import (
    append_chat_message_pair,
    conversation_detail,
    get_owned_conversation,
    get_user_settings,
    message_read,
)
from app.core.db import get_async_session
from app.models.conversation import Conversation
from app.models.user import User
from app.models.voice import VoiceSession, VoiceSessionStatus
from app.schemas.voice import (
    VoiceMessageRequest,
    VoiceMessageResponse,
    VoiceSessionAttachRequest,
    VoiceSessionAttachResponse,
    VoiceSessionCreate,
    VoiceSessionCreateResponse,
    VoiceSessionEndResponse,
)

router = APIRouter(prefix="/voice", tags=["voice"])
VOICE_SESSION_LIFETIME = timedelta(hours=2)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(session: VoiceSession) -> bool:
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= _now()


async def _get_voice_session_by_token(
    token: str | None,
    db: AsyncSession,
) -> VoiceSession:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing voice session token")

    result = await db.execute(select(VoiceSession).where(VoiceSession.token_hash == _token_hash(token)))
    voice_session = result.scalar_one_or_none()
    if voice_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid voice session token")
    if voice_session.status != VoiceSessionStatus.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Voice session is not active")
    if _is_expired(voice_session):
        voice_session.status = VoiceSessionStatus.ended
        voice_session.ended_at = _now()
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Voice session expired")
    return voice_session


async def _get_voice_user_and_conversation(
    voice_session: VoiceSession,
    db: AsyncSession,
) -> tuple[User, Conversation]:
    user_result = await db.execute(select(User).where(User.id == voice_session.user_id, User.is_active == True))  # noqa: E712
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Voice session user is not active")

    conversation_result = await db.execute(
        select(Conversation)
        .where(Conversation.id == voice_session.conversation_id, Conversation.user_id == voice_session.user_id)
        .options(selectinload(Conversation.messages))
        .execution_options(populate_existing=True)
    )
    conversation = conversation_result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice conversation not found")
    return user, conversation


@router.post("/sessions", response_model=VoiceSessionCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_voice_session(
    payload: VoiceSessionCreate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> VoiceSessionCreateResponse:
    if payload.conversation_id:
        conversation = await get_owned_conversation(payload.conversation_id, user, db)
    else:
        conversation = Conversation(user_id=user.id, title="Hlasový hovor")
        db.add(conversation)
        await db.flush()

    token = secrets.token_urlsafe(32)
    expires_at = _now() + VOICE_SESSION_LIFETIME
    voice_session = VoiceSession(
        id=uuid.uuid4(),
        user_id=user.id,
        conversation_id=conversation.id,
        token_hash=_token_hash(token),
        status=VoiceSessionStatus.active,
        expires_at=expires_at,
    )
    db.add(voice_session)
    await db.commit()

    conversation = await get_owned_conversation(conversation.id, user, db)
    return VoiceSessionCreateResponse(
        voice_session_id=voice_session.id,
        token=token,
        conversation=conversation_detail(conversation),
        expires_at=voice_session.expires_at,
    )


@router.post("/sessions/attach", response_model=VoiceSessionAttachResponse)
async def attach_voice_session(
    payload: VoiceSessionAttachRequest,
    x_voice_session_token: str | None = Header(default=None, alias="X-Voice-Session-Token"),
    db: AsyncSession = Depends(get_async_session),
) -> VoiceSessionAttachResponse:
    voice_session = await _get_voice_session_by_token(x_voice_session_token, db)
    voice_session.speechcloud_session_id = payload.speechcloud_session_id
    user_settings = await get_user_settings(voice_session.user_id, db)
    await db.commit()
    await db.refresh(voice_session)
    return VoiceSessionAttachResponse(
        voice_session_id=voice_session.id,
        conversation_id=voice_session.conversation_id,
        status=voice_session.status,
        expires_at=voice_session.expires_at,
        tts_voice=user_settings.tts_voice,
    )


@router.post("/messages", response_model=VoiceMessageResponse)
async def send_voice_message(
    payload: VoiceMessageRequest,
    x_voice_session_token: str | None = Header(default=None, alias="X-Voice-Session-Token"),
    db: AsyncSession = Depends(get_async_session),
) -> VoiceMessageResponse:
    voice_session = await _get_voice_session_by_token(x_voice_session_token, db)
    user, conversation = await _get_voice_user_and_conversation(voice_session, db)
    updated_conversation, user_message, assistant_message = await append_chat_message_pair(
        session=db,
        conversation=conversation,
        user=user,
        content=payload.content,
        model=payload.model,
        response_mode="speech",
    )
    return VoiceMessageResponse(
        conversation=conversation_detail(updated_conversation),
        user_message=message_read(user_message),
        assistant_message=message_read(assistant_message),
    )


@router.post("/sessions/{voice_session_id}/end", response_model=VoiceSessionEndResponse)
async def end_voice_session(
    voice_session_id: uuid.UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> VoiceSessionEndResponse:
    result = await db.execute(
        select(VoiceSession).where(VoiceSession.id == voice_session_id, VoiceSession.user_id == user.id)
    )
    voice_session = result.scalar_one_or_none()
    if voice_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice session not found")
    voice_session.status = VoiceSessionStatus.ended
    voice_session.ended_at = voice_session.ended_at or _now()
    await db.commit()
    await db.refresh(voice_session)
    return VoiceSessionEndResponse(voice_session_id=voice_session.id, status=voice_session.status)
