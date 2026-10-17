from typing import Literal

from pydantic import BaseModel, Field


class ProcessingOptions(BaseModel):
    ocr_engine: Literal["easyocr", "tesseract", "ollama"] = "easyocr"
    ocr_model: str | None = Field(default=None, max_length=160)
    ocr_prompt: str = Field(default="Text Recognition:", min_length=1, max_length=4000)
    extraction_mode: Literal["vision_hybrid", "text_only"] = "vision_hybrid"
    rag_search_limit: int = Field(default=5, ge=1, le=50)
    reranker_candidate_limit: int = Field(default=10, ge=1, le=50)
    inference_timeout_seconds: int = Field(default=180, ge=10, le=1800)
