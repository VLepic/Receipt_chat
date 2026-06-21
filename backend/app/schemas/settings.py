import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RagSourceStrategy = Literal["best_band", "top_n"]


class UserSettingsRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    default_chat_model: str | None
    tts_voice: str | None
    ocr_processing_model: str | None
    rag_source_strategy: RagSourceStrategy
    rag_best_band: float
    rag_top_n: int
    created_at: datetime
    updated_at: datetime


class UserSettingsUpdate(BaseModel):
    default_chat_model: str | None = Field(default=None, max_length=120)
    tts_voice: str | None = Field(default=None, max_length=120)
    ocr_processing_model: str | None = Field(default=None, max_length=120)
    rag_source_strategy: RagSourceStrategy = "best_band"
    rag_best_band: float = Field(default=0.08, ge=0.0, le=1.0)
    rag_top_n: int = Field(default=2, ge=1, le=10)
