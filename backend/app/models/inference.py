from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class InferenceRoutingSettings(Base):
    __tablename__ = "inference_routing_settings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default="default")
    chat_server_id: Mapped[str] = mapped_column(String(40), default="server_1")
    embedding_server_id: Mapped[str] = mapped_column(String(40), default="server_1")
    embedding_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reranker_server_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reranker_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    ocr_server_id: Mapped[str] = mapped_column(String(40), default="server_1")
    structuring_server_id: Mapped[str] = mapped_column(String(40), default="server_1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
