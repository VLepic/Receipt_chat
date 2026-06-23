import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UserSettings(Base):
    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_settings_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True
    )
    default_chat_model: Mapped[str | None] = mapped_column(String(120), default=None)
    tts_voice: Mapped[str | None] = mapped_column(String(120), default=None)
    ocr_processing_model: Mapped[str | None] = mapped_column(String(120), default=None)
    rag_source_strategy: Mapped[str] = mapped_column(String(40), default="best_band")
    rag_best_band: Mapped[float] = mapped_column(Float, default=0.08)
    rag_reranker_best_band: Mapped[float] = mapped_column(Float, default=0.10)
    rag_reranker_min_score: Mapped[float] = mapped_column(Float, default=0.50)
    rag_top_n: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
