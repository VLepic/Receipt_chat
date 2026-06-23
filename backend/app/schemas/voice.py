import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.chat import ConversationDetail, MessageRead


class VoiceSessionCreate(BaseModel):
    conversation_id: uuid.UUID | None = None


class VoiceSessionCreateResponse(BaseModel):
    voice_session_id: uuid.UUID
    token: str
    conversation: ConversationDetail
    expires_at: datetime


class VoiceSessionAttachRequest(BaseModel):
    speechcloud_session_id: str = Field(min_length=1, max_length=160)


class VoiceSessionAttachResponse(BaseModel):
    voice_session_id: uuid.UUID
    conversation_id: uuid.UUID
    status: str
    expires_at: datetime
    tts_voice: str | None


class VoiceMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    model: str | None = Field(default=None, max_length=120)


class VoiceMessageResponse(BaseModel):
    conversation: ConversationDetail
    user_message: MessageRead
    assistant_message: MessageRead


class VoiceSessionEndResponse(BaseModel):
    voice_session_id: uuid.UUID
    status: str
