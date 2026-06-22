import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChatSource(BaseModel):
    document_id: uuid.UUID
    title: str
    filename: str | None = None
    distance: float | None = None
    reranker_score: float | None = None


class ChatRetrieval(BaseModel):
    mode: str = "none"
    used_rag: bool = False
    used_search: bool = False
    used_reranker: bool = False
    reranker_model: str | None = None
    source_count: int = 0


class MessageRead(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    model: str | None
    created_at: datetime
    sources: list[ChatSource] = Field(default_factory=list)
    retrieval: ChatRetrieval | None = None


class ConversationRead(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[MessageRead]


class ConversationCreate(BaseModel):
    title: str = Field(default="Nova konverzace", max_length=160)


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    model: str | None = Field(default=None, max_length=120)


class ChatResponse(BaseModel):
    conversation: ConversationDetail
    assistant_message: MessageRead


class OllamaModelRead(BaseModel):
    name: str
    selected: bool = False
