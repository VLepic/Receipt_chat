from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "SP2 Assistant"
    environment: str = "local"
    secret_key: str = Field(default="change-me-in-env")
    database_url: str = Field(
        default="postgresql+asyncpg://sp2:sp2@postgres:5432/sp2"
    )
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://127.0.0.1:5173"])

    cookie_name: str = "sp2_session"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "phi4"
    ollama_username: str | None = None
    ollama_password: str | None = None
    ollama_auth_scheme: str = "digest"
    ollama_timeout_seconds: float = 60.0
    ollama_server_1_name: str = "Server 1"
    ollama_server_2_name: str = "Server 2"
    ollama_server_2_base_url: str | None = None
    ollama_server_2_username: str | None = None
    ollama_server_2_password: str | None = None
    ollama_server_2_auth_scheme: str = "digest"

    document_storage_dir: str = "storage/documents"
    document_max_upload_bytes: int = 10 * 1024 * 1024

    ocr_language: str = "ces+eng"
    ocr_engine: str = "easyocr"
    ollama_ocr_model: str = "glm-ocr:latest"
    ollama_ocr_prompt: str = "Text Recognition:"
    ollama_ocr_timeout_seconds: float = 180.0
    easyocr_languages: str = "cs,en"
    easyocr_max_image_side: int = 1800
    ocr_worker_poll_seconds: float = 5.0
    extraction_model: str | None = None
    extraction_mode: str = "vision_hybrid"
    extraction_max_images: int = 4
    extraction_image_max_side: int = 1800
    rag_embedding_model: str | None = None
    rag_reranker_model: str | None = None
    rag_reranker_candidate_limit: int = 10
    rag_reranker_timeout_seconds: float = 180.0
    rag_search_limit: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
