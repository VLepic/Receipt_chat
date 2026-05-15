import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_active_user
from app.core.config import settings
from app.core.db import get_async_session
from app.models.document import Document, DocumentExtraction, DocumentFile, DocumentStatus, OcrResult
from app.models.job import JobKind, JobStatus, ProcessingJob
from app.models.user import User
from app.schemas.document import DocumentExtractionRead, DocumentExtractionUpdate, DocumentFileRead, DocumentRead, OcrResultRead
from app.schemas.job import ProcessingJobRead
from app.services.extraction import build_structured_rag_text, process_extraction_job
from app.services.ocr import process_ocr_job
from app.services.vector_store import delete_document_chunks, index_document_rag_text

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_MIME_BY_MAGIC = {
    "image/png": b"\x89PNG\r\n\x1a\n",
    "application/pdf": b"%PDF-",
}


def _detect_mime_type(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"

    for mime_type, signature in ALLOWED_MIME_BY_MAGIC.items():
        if content.startswith(signature):
            return mime_type
    return None


def _storage_extension(mime_type: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "application/pdf": ".pdf",
    }[mime_type]


def _safe_filename(filename: str | None) -> str:
    name = Path(filename or "document").name.strip() or "document"
    return name[:255]


async def _get_owned_document(document_id: uuid.UUID, user: User, session: AsyncSession) -> Document:
    result = await session.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


async def _read_validated_upload(file: UploadFile) -> tuple[bytes, str]:
    content = await file.read(settings.document_max_upload_bytes + 1)
    if len(content) > settings.document_max_upload_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File is too large")
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty")

    detected_mime_type = _detect_mime_type(content)
    if detected_mime_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Upload PNG, JPEG or PDF.",
        )
    return content, detected_mime_type


async def _clear_document_outputs(document_id: uuid.UUID, user_id: uuid.UUID, session: AsyncSession) -> None:
    await delete_document_chunks(session, document_id)
    await session.execute(delete(DocumentExtraction).where(DocumentExtraction.document_id == document_id))
    await session.execute(delete(OcrResult).where(OcrResult.document_id == document_id, OcrResult.user_id == user_id))


def _queue_ocr_job(document: Document, session: AsyncSession, payload: dict | None = None) -> None:
    session.add(
        ProcessingJob(
            user_id=document.user_id,
            document_id=document.id,
            kind=JobKind.ocr,
            status=JobStatus.queued,
            payload=payload or {"filename": document.filename, "mime_type": document.mime_type},
        )
    )


async def _next_file_sort_order(document_id: uuid.UUID, session: AsyncSession) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(DocumentFile.sort_order), -1)).where(DocumentFile.document_id == document_id)
    )
    return int(result.scalar_one()) + 1


def _build_file_path(user_id: uuid.UUID, document_id: uuid.UUID, file_id: uuid.UUID, mime_type: str) -> Path:
    return (
        Path(settings.document_storage_dir)
        / str(user_id)
        / str(document_id)
        / f"{file_id}{_storage_extension(mime_type)}"
    )


@router.get("", response_model=list[DocumentRead])
async def list_documents(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[Document]:
    result = await session.execute(
        select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> Document:
    return await _get_owned_document(document_id, user, session)


@router.get("/{document_id}/files", response_model=list[DocumentFileRead])
async def list_document_files(
    document_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[DocumentFile]:
    await _get_owned_document(document_id, user, session)
    result = await session.execute(
        select(DocumentFile)
        .where(DocumentFile.document_id == document_id, DocumentFile.user_id == user.id)
        .order_by(DocumentFile.sort_order, DocumentFile.created_at)
    )
    return list(result.scalars().all())


@router.post("/{document_id}/files", response_model=DocumentFileRead, status_code=status.HTTP_201_CREATED)
async def add_document_file(
    document_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> DocumentFile:
    document = await _get_owned_document(document_id, user, session)
    content, detected_mime_type = await _read_validated_upload(file)
    file_id = uuid.uuid4()
    storage_path = _build_file_path(user.id, document.id, file_id, detected_mime_type)

    try:
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(content)
        document_file = DocumentFile(
            id=file_id,
            document_id=document.id,
            user_id=user.id,
            filename=_safe_filename(file.filename),
            mime_type=detected_mime_type,
            storage_path=str(storage_path),
            sort_order=await _next_file_sort_order(document.id, session),
        )
        session.add(document_file)
        await _clear_document_outputs(document.id, user.id, session)
        document.status = DocumentStatus.uploaded
        _queue_ocr_job(
            document,
            session,
            payload={"filename": document_file.filename, "mime_type": document_file.mime_type, "action": "file_added"},
        )
        await session.commit()
        await session.refresh(document_file)
        return document_file
    except Exception:
        if storage_path.exists():
            storage_path.unlink()
        raise


@router.delete("/{document_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document_file(
    document_id: uuid.UUID,
    file_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    document = await _get_owned_document(document_id, user, session)
    count_result = await session.execute(
        select(func.count(DocumentFile.id)).where(DocumentFile.document_id == document.id, DocumentFile.user_id == user.id)
    )
    if int(count_result.scalar_one()) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the last file. Delete the whole document instead.",
        )

    file_result = await session.execute(
        select(DocumentFile).where(
            DocumentFile.id == file_id,
            DocumentFile.document_id == document.id,
            DocumentFile.user_id == user.id,
        )
    )
    document_file = file_result.scalar_one_or_none()
    if document_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file not found")

    storage_path = Path(document_file.storage_path)
    await session.delete(document_file)
    await _clear_document_outputs(document.id, user.id, session)
    document.status = DocumentStatus.uploaded
    _queue_ocr_job(document, session, payload={"filename": document_file.filename, "action": "file_deleted"})
    await session.commit()
    if storage_path.exists():
        storage_path.unlink()


@router.get("/{document_id}/jobs", response_model=list[ProcessingJobRead])
async def list_document_jobs(
    document_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[ProcessingJob]:
    document_result = await session.execute(
        select(Document.id).where(Document.id == document_id, Document.user_id == user.id)
    )
    if document_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    result = await session.execute(
        select(ProcessingJob)
        .where(ProcessingJob.document_id == document_id, ProcessingJob.user_id == user.id)
        .order_by(ProcessingJob.created_at.desc())
    )
    return list(result.scalars().all())


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    document = await _get_owned_document(document_id, user, session)
    files_result = await session.execute(
        select(DocumentFile.storage_path).where(DocumentFile.document_id == document.id, DocumentFile.user_id == user.id)
    )
    file_paths = [Path(path) for path in files_result.scalars().all()]
    if document.storage_path:
        file_paths.append(Path(document.storage_path))

    await delete_document_chunks(session, document.id)
    await session.execute(delete(ProcessingJob).where(ProcessingJob.document_id == document.id, ProcessingJob.user_id == user.id))
    await session.execute(delete(DocumentExtraction).where(DocumentExtraction.document_id == document.id))
    await session.execute(delete(OcrResult).where(OcrResult.document_id == document.id, OcrResult.user_id == user.id))
    await session.execute(delete(DocumentFile).where(DocumentFile.document_id == document.id, DocumentFile.user_id == user.id))
    await session.delete(document)
    await session.commit()

    for path in dict.fromkeys(file_paths):
        if path.exists():
            path.unlink()


@router.get("/{document_id}/ocr", response_model=OcrResultRead)
async def get_document_ocr_result(
    document_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> OcrResult:
    document_result = await session.execute(
        select(Document.id).where(Document.id == document_id, Document.user_id == user.id)
    )
    if document_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    result = await session.execute(
        select(OcrResult).where(OcrResult.document_id == document_id, OcrResult.user_id == user.id)
    )
    ocr_result = result.scalar_one_or_none()
    if ocr_result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OCR result not found")
    return ocr_result


@router.post("/{document_id}/ocr/run", response_model=ProcessingJobRead)
async def run_document_ocr(
    document_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> ProcessingJob:
    result = await session.execute(
        select(ProcessingJob)
        .where(
            ProcessingJob.document_id == document_id,
            ProcessingJob.user_id == user.id,
            ProcessingJob.kind == JobKind.ocr,
        )
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OCR job not found")
    processed_job = await process_ocr_job(session, job.id)
    if processed_job.status == JobStatus.succeeded:
        session.add(
            ProcessingJob(
                user_id=user.id,
                document_id=document_id,
                kind=JobKind.extraction,
                status=JobStatus.queued,
                payload={"source_job_id": str(processed_job.id)},
            )
        )
        await session.commit()
    return processed_job


@router.get("/{document_id}/extraction", response_model=DocumentExtractionRead)
async def get_document_extraction(
    document_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> DocumentExtraction:
    document_result = await session.execute(
        select(Document.id).where(Document.id == document_id, Document.user_id == user.id)
    )
    if document_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    result = await session.execute(
        select(DocumentExtraction).where(DocumentExtraction.document_id == document_id, DocumentExtraction.user_id == user.id)
    )
    extraction = result.scalar_one_or_none()
    if extraction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document extraction not found")
    return extraction


@router.put("/{document_id}/extraction", response_model=DocumentExtractionRead)
async def update_document_extraction(
    document_id: uuid.UUID,
    payload: DocumentExtractionUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> DocumentExtraction:
    document = await _get_owned_document(document_id, user, session)

    extraction_result = await session.execute(
        select(DocumentExtraction).where(DocumentExtraction.document_id == document_id, DocumentExtraction.user_id == user.id)
    )
    extraction = extraction_result.scalar_one_or_none()
    if extraction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document extraction not found")

    ocr_result_result = await session.execute(
        select(OcrResult).where(OcrResult.document_id == document_id, OcrResult.user_id == user.id)
    )
    ocr_result = ocr_result_result.scalar_one_or_none()
    if ocr_result is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OCR result is required before saving extraction")

    structured = payload.structured_json
    extraction.structured_json = structured
    extraction.summary = str(structured.get("summary") or "")
    extraction.review_status = "approved"
    ocr_result.rag_text = build_structured_rag_text(document, ocr_result, structured)
    await index_document_rag_text(session, document, ocr_result.rag_text, structured)
    await session.commit()
    await session.refresh(extraction)
    return extraction


@router.post("/{document_id}/extraction/run", response_model=ProcessingJobRead)
async def run_document_extraction(
    document_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> ProcessingJob:
    document_result = await session.execute(
        select(Document.id).where(Document.id == document_id, Document.user_id == user.id)
    )
    if document_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    result = await session.execute(
        select(ProcessingJob)
        .where(
            ProcessingJob.document_id == document_id,
            ProcessingJob.user_id == user.id,
            ProcessingJob.kind == JobKind.extraction,
        )
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        job = ProcessingJob(
            user_id=user.id,
            document_id=document_id,
            kind=JobKind.extraction,
            status=JobStatus.queued,
            payload={"manual": True},
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
    return await process_extraction_job(session, job.id)


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> Document:
    content, detected_mime_type = await _read_validated_upload(file)
    document_id = uuid.uuid4()
    file_id = uuid.uuid4()
    storage_path = _build_file_path(user.id, document_id, file_id, detected_mime_type)

    try:
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(content)

        document = Document(
            id=document_id,
            user_id=user.id,
            filename=_safe_filename(file.filename),
            mime_type=detected_mime_type,
            storage_path=str(storage_path),
            status=DocumentStatus.uploaded,
        )
        session.add(document)
        await session.flush()
        session.add(
            DocumentFile(
                id=file_id,
                document_id=document.id,
                user_id=user.id,
                filename=document.filename,
                mime_type=detected_mime_type,
                storage_path=str(storage_path),
                sort_order=0,
            )
        )
        _queue_ocr_job(document, session)
        await session.commit()
        await session.refresh(document)
        return document
    except Exception:
        if storage_path.exists():
            storage_path.unlink()
        raise
