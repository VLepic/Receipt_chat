from typing import Literal

from pydantic import BaseModel, Field

InferenceRole = Literal["chat", "embedding", "reranker", "ocr", "structuring"]


class InferenceRoutingUpdate(BaseModel):
    chat_server_id: str
    embedding_server_id: str
    embedding_model: str | None = Field(default=None, max_length=160)
    reranker_server_id: str | None = None
    reranker_model: str | None = Field(default=None, max_length=160)
    ocr_server_id: str
    structuring_server_id: str


class InferenceServerRead(BaseModel):
    id: str
    name: str
    reachable: bool
    models: list[str]
    detail: str | None = None


class InferenceRoutingRead(InferenceRoutingUpdate):
    pass


class InferenceConfigurationRead(BaseModel):
    servers: list[InferenceServerRead]
    routing: InferenceRoutingRead
    reranker_enabled: bool
