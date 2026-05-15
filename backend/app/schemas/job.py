import uuid
from datetime import datetime

from pydantic import BaseModel


class ProcessingJobRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID | None
    kind: str
    status: str
    payload: dict
    error_message: str | None
    created_at: datetime
    updated_at: datetime
