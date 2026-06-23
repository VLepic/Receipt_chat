import re
import base64
import subprocess
import tempfile
import uuid
import warnings
from dataclasses import dataclass, replace
from pathlib import Path

import httpx
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.document import Document, DocumentFile, DocumentStatus, OcrResult
from app.models.job import JobKind, JobStatus, ProcessingJob
from app.services.ollama_auth import ollama_auth
from app.services.inference_routing import get_role_server
from app.services.ollama_servers import OllamaServerConfig, get_ollama_server


@dataclass(frozen=True)
class ExtractedText:
    raw_text: str
    normalized_text: str
    rag_text: str
    metadata_json: dict
    language: str
    page_count: int
    engine: str


DATE_PATTERN = re.compile(r"\b(?:\d{1,2}[.\/-]\d{1,2}[.\/-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2})\b")
AMOUNT_PATTERN = re.compile(r"\b\d{1,3}(?:[ .]\d{3})*(?:[,.]\d{2})\b")
NOISE_PATTERN = re.compile(r"^[\W_]+$")


def normalize_ocr_text(text: str) -> str:
    lines = []
    for line in text.replace("\x0c", "\n").splitlines():
        cleaned = " ".join(line.split()).strip()
        if not cleaned or NOISE_PATTERN.match(cleaned):
            continue
        lines.append(cleaned)
    return "\n".join(lines).strip()


def build_ocr_metadata(normalized_text: str) -> dict:
    date_matches = list(DATE_PATTERN.finditer(normalized_text))
    date_spans = [match.span() for match in date_matches]
    dates = list(dict.fromkeys(match.group(0) for match in date_matches))[:10]
    amount_candidates = []
    for match in AMOUNT_PATTERN.finditer(normalized_text):
        start, end = match.span()
        if any(start >= date_start and end <= date_end for date_start, date_end in date_spans):
            continue
        amount_candidates.append(match.group(0))
    amounts = list(dict.fromkeys(amount_candidates))[:20]
    return {
        "dates": dates,
        "amounts": amounts,
        "line_count": len([line for line in normalized_text.splitlines() if line.strip()]),
    }


def build_rag_text(document: Document, normalized_text: str, metadata: dict) -> str:
    sections = [
        f"Soubor: {document.filename}",
        f"Typ dokumentu: {document.mime_type}",
    ]
    if metadata.get("file_count"):
        sections.append(f"Pocet souboru: {metadata['file_count']}")
    if metadata.get("filenames"):
        sections.append(f"Cast dokladu: {', '.join(metadata['filenames'])}")
    if metadata.get("dates"):
        sections.append(f"Kandidati datumu: {', '.join(metadata['dates'])}")
    if metadata.get("amounts"):
        sections.append(f"Kandidati castek: {', '.join(metadata['amounts'][:8])}")
    sections.append("OCR text:")
    sections.append(normalized_text)
    return "\n".join(sections).strip()


class OcrEngine:
    def extract(self, document: Document) -> ExtractedText:
        raise NotImplementedError


class MultiFileOcrEngine(OcrEngine):
    def extract(self, document: Document) -> ExtractedText:
        files = list(getattr(document, "files", []) or [])
        if not files:
            files = [
                DocumentFile(
                    document_id=document.id,
                    user_id=document.user_id,
                    filename=document.filename,
                    mime_type=document.mime_type,
                    storage_path=document.storage_path,
                    sort_order=0,
                )
            ]

        raw_parts = []
        page_count = 0
        filenames = []
        for document_file in sorted(files, key=lambda item: item.sort_order):
            file_raw_text, file_page_count = self._extract_file(document_file)
            raw_parts.append(f"--- Soubor: {document_file.filename} ---\n{file_raw_text}")
            page_count += file_page_count
            filenames.append(document_file.filename)

        raw_text = "\n\n".join(raw_parts)
        normalized_text = normalize_ocr_text(raw_text)
        if not normalized_text:
            raise ValueError("OCR returned empty text")
        metadata = build_ocr_metadata(normalized_text)
        metadata["file_count"] = len(files)
        metadata["filenames"] = filenames

        return ExtractedText(
            raw_text=raw_text,
            normalized_text=normalized_text,
            rag_text=build_rag_text(document, normalized_text, metadata),
            metadata_json=metadata,
            language=settings.ocr_language,
            page_count=max(page_count, 1),
            engine=self.engine_name,
        )

    def _extract_file(self, document_file: DocumentFile) -> tuple[str, int]:
        raise NotImplementedError


class TesseractOcrEngine(MultiFileOcrEngine):
    engine_name = "tesseract"

    def _extract_file(self, document_file: DocumentFile) -> tuple[str, int]:
        path = Path(document_file.storage_path)
        if not path.exists():
            raise FileNotFoundError(f"Document file not found: {path}")

        if document_file.mime_type == "application/pdf":
            return self._extract_pdf(path)
        return self._run_tesseract(path), 1

    def _extract_pdf(self, path: Path) -> tuple[str, int]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_prefix = Path(tmp_dir) / "page"
            subprocess.run(
                ["pdftoppm", "-png", "-r", "220", str(path), str(output_prefix)],
                check=True,
                capture_output=True,
                text=True,
            )
            pages = sorted(Path(tmp_dir).glob("page-*.png"))
            texts = [self._run_tesseract(page) for page in pages]
            return "\n\n".join(texts), max(len(pages), 1)

    def _run_tesseract(self, path: Path) -> str:
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", settings.ocr_language],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout


class EasyOcrEngine(MultiFileOcrEngine):
    engine_name = "easyocr"
    _reader = None

    def _extract_file(self, document_file: DocumentFile) -> tuple[str, int]:
        path = Path(document_file.storage_path)
        if not path.exists():
            raise FileNotFoundError(f"Document file not found: {path}")

        if document_file.mime_type == "application/pdf":
            return self._extract_pdf(path)
        return self._run_easyocr(path), 1

    def _extract_pdf(self, path: Path) -> tuple[str, int]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_prefix = Path(tmp_dir) / "page"
            subprocess.run(
                ["pdftoppm", "-png", "-r", "260", str(path), str(output_prefix)],
                check=True,
                capture_output=True,
                text=True,
            )
            pages = sorted(Path(tmp_dir).glob("page-*.png"))
            texts = [self._run_easyocr(page) for page in pages]
            return "\n\n".join(texts), max(len(pages), 1)

    def _run_easyocr(self, path: Path) -> str:
        reader = self._get_reader()
        with tempfile.TemporaryDirectory() as tmp_dir:
            prepared_path = self._prepare_image(path, Path(tmp_dir))
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="'pin_memory' argument is set as true.*")
                lines = reader.readtext(str(prepared_path), detail=0, paragraph=False)
        return "\n".join(str(line) for line in lines if str(line).strip())

    def _prepare_image(self, path: Path, tmp_dir: Path) -> Path:
        image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        image.thumbnail((settings.easyocr_max_image_side, settings.easyocr_max_image_side))
        prepared_path = tmp_dir / f"{path.stem}.png"
        image.save(prepared_path)
        return prepared_path

    @classmethod
    def _get_reader(cls):
        if cls._reader is None:
            try:
                import easyocr
            except ImportError as exc:
                raise RuntimeError("EasyOCR is not installed in this backend image") from exc

            languages = [item.strip() for item in settings.easyocr_languages.split(",") if item.strip()]
            cls._reader = easyocr.Reader(languages or ["cs", "en"], gpu=False)
        return cls._reader


class OllamaOcrEngine(MultiFileOcrEngine):
    engine_name = "ollama"

    def __init__(self, server: OllamaServerConfig | None = None) -> None:
        self.server = server or get_ollama_server("server_1")

    def extract(self, document: Document) -> ExtractedText:
        extracted = super().extract(document)
        return replace(
            extracted,
            metadata_json={
                **extracted.metadata_json,
                "ollama_model": settings.ollama_ocr_model,
                "ollama_prompt": settings.ollama_ocr_prompt,
            },
            engine=f"ollama:{settings.ollama_ocr_model}",
        )

    def _extract_file(self, document_file: DocumentFile) -> tuple[str, int]:
        path = Path(document_file.storage_path)
        if not path.exists():
            raise FileNotFoundError(f"Document file not found: {path}")

        if document_file.mime_type == "application/pdf":
            return self._extract_pdf(path)
        return self._run_ollama_ocr(path), 1

    def _extract_pdf(self, path: Path) -> tuple[str, int]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_prefix = Path(tmp_dir) / "page"
            subprocess.run(
                ["pdftoppm", "-png", "-r", "260", str(path), str(output_prefix)],
                check=True,
                capture_output=True,
                text=True,
            )
            pages = sorted(Path(tmp_dir).glob("page-*.png"))
            texts = [self._run_ollama_ocr(page) for page in pages]
            return "\n\n".join(texts), max(len(pages), 1)

    def _run_ollama_ocr(self, path: Path) -> str:
        image_payload = base64.b64encode(path.read_bytes()).decode("ascii")
        payload = {
            "model": settings.ollama_ocr_model,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": settings.ollama_ocr_prompt,
                    "images": [image_payload],
                }
            ],
        }
        try:
            with httpx.Client(timeout=settings.ollama_ocr_timeout_seconds, auth=self._auth()) as client:
                response = client.post(f"{self.server.base_url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise RuntimeError("Ollama OCR timeout") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("Ollama OCR server error") from exc

        content = data.get("message", {}).get("content")
        if not content or not content.strip():
            raise ValueError("Ollama OCR returned empty text")
        return content.strip()

    def _auth(self) -> httpx.Auth | None:
        return ollama_auth(self.server)


def create_ocr_engine(server: OllamaServerConfig | None = None) -> OcrEngine:
    engine_name = settings.ocr_engine.strip().lower()
    if engine_name == "easyocr":
        return EasyOcrEngine()
    if engine_name == "tesseract":
        return TesseractOcrEngine()
    if engine_name == "ollama":
        return OllamaOcrEngine(server)
    raise ValueError(f"Unsupported OCR engine: {settings.ocr_engine}")


async def process_ocr_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    engine: OcrEngine | None = None,
) -> ProcessingJob:
    result = await session.execute(
        select(ProcessingJob).where(ProcessingJob.id == job_id, ProcessingJob.kind == JobKind.ocr)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise ValueError("OCR job not found")

    document_result = await session.execute(
        select(Document)
        .where(Document.id == job.document_id, Document.user_id == job.user_id)
        .options(selectinload(Document.files))
    )
    document = document_result.scalar_one_or_none()
    if document is None:
        job.status = JobStatus.failed
        job.error_message = "Document not found"
        await session.commit()
        return job

    job.status = JobStatus.running
    job.error_message = None
    document.status = DocumentStatus.processing
    await session.commit()

    try:
        if engine is None:
            engine = create_ocr_engine(await get_role_server(session, "ocr"))
        extracted = engine.extract(document)
        existing_result = await session.execute(
            select(OcrResult).where(OcrResult.document_id == document.id, OcrResult.user_id == document.user_id)
        )
        ocr_result = existing_result.scalar_one_or_none()
        if ocr_result is None:
            ocr_result = OcrResult(
                id=uuid.uuid4(),
                document_id=document.id,
                user_id=document.user_id,
                raw_text="",
                normalized_text="",
                rag_text="",
                metadata_json={},
                language="",
                page_count=1,
                engine="",
            )
            session.add(ocr_result)

        ocr_result.raw_text = extracted.raw_text
        ocr_result.normalized_text = extracted.normalized_text
        ocr_result.rag_text = extracted.rag_text
        ocr_result.metadata_json = extracted.metadata_json
        ocr_result.language = extracted.language
        ocr_result.page_count = extracted.page_count
        ocr_result.engine = extracted.engine
        document.status = DocumentStatus.processed
        job.status = JobStatus.succeeded
        job.payload = {**(job.payload or {}), "ocr_result_id": str(ocr_result.id)}
    except Exception as exc:
        document.status = DocumentStatus.failed
        job.status = JobStatus.failed
        job.error_message = str(exc)

    await session.commit()
    await session.refresh(job)
    return job


async def process_next_ocr_job(session: AsyncSession, engine: OcrEngine | None = None) -> ProcessingJob | None:
    result = await session.execute(
        select(ProcessingJob)
        .where(ProcessingJob.kind == JobKind.ocr, ProcessingJob.status == JobStatus.queued)
        .order_by(ProcessingJob.created_at)
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None
    return await process_ocr_job(session, job.id, engine=engine)
