import uuid
from datetime import datetime

from pydantic import BaseModel


class DocumentRead(BaseModel):
    id: uuid.UUID
    filename: str
    mime_type: str
    status: str
    created_at: datetime
    updated_at: datetime


class DocumentFileRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    mime_type: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class OcrResultRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    raw_text: str
    normalized_text: str
    rag_text: str
    metadata_json: dict
    language: str
    page_count: int
    engine: str
    created_at: datetime
    updated_at: datetime


class DocumentExtractionRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    structured_json: dict
    summary: str
    review_status: str
    model: str
    raw_response: str
    created_at: datetime
    updated_at: datetime


class DocumentExtractionUpdate(BaseModel):
    structured_json: dict
