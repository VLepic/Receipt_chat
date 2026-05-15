import asyncio
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import async_session_maker
from app.main import app
from app.models.document import Document, DocumentExtraction, DocumentFile, OcrResult
from app.models.job import ProcessingJob
from app.services.ocr import (
    EasyOcrEngine,
    ExtractedText,
    OllamaOcrEngine,
    TesseractOcrEngine,
    build_ocr_metadata,
    create_ocr_engine,
    normalize_ocr_text,
)

PASSWORD = "StrongPass123"


def _register_and_login(client: TestClient, email: str) -> None:
    register_response = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert register_response.status_code in {200, 201}, register_response.text

    login_response = client.post(
        "/api/auth/login",
        data={"username": email, "password": PASSWORD},
    )
    assert login_response.status_code in {200, 204}, login_response.text


def _minimal_extraction_json(summary: str = "Testovaci doklad.") -> str:
    return f"""
    {{
      "document_type": "receipt",
      "issue_date": "2026-05-12",
      "taxable_supply_date": null,
      "due_date": null,
      "invoice_number": null,
      "delivery_note_number": null,
      "merchant": {{"name": "Test Shop", "ico": null, "dic": null, "registered_address": {{"raw": null, "street": null, "city": null, "postal_code": null, "country": null}}, "store_address": {{"raw": null, "street": null, "city": null, "postal_code": null, "country": null}}}},
      "order": {{"order_number": null, "order_date": null}},
      "payment": {{"total": {{"amount": 123.0, "raw": "123,00 Kc"}}, "payment_method": null, "currency": "CZK", "bank_account": {{"account_number": null, "iban": null, "swift": null, "bank_name": null}}, "variable_symbol": null, "constant_symbol": null}},
      "buyer": {{"name": null, "ico": null, "dic": null, "billing_address": {{"raw": null, "street": null, "city": null, "postal_code": null, "country": null}}, "delivery_address": {{"raw": null, "street": null, "city": null, "postal_code": null, "country": null}}}},
      "items": [],
      "tax_summary": [],
      "summary": "{summary}",
      "confidence": {{}},
      "needs_review": true,
      "evidence": {{}}
    }}
    """


def _fake_extracted_text(text: str = "Datum 12.05.2026\nCelkem 123,00 Kc") -> ExtractedText:
    return ExtractedText(
        raw_text=text,
        normalized_text=text,
        rag_text=f"OCR text:\n{text}",
        metadata_json={"dates": ["12.05.2026"], "amounts": ["123,00"], "line_count": 2},
        language="ces+eng",
        page_count=1,
        engine="fake-tesseract",
    )


def _document_integrity_snapshot(document_id: str | uuid.UUID) -> dict:
    document_uuid = uuid.UUID(str(document_id))

    async def read_snapshot() -> dict:
        async with async_session_maker() as session:
            document_count = (
                await session.execute(select(Document).where(Document.id == document_uuid))
            ).scalars().all()
            files = (
                await session.execute(
                    select(DocumentFile).where(DocumentFile.document_id == document_uuid).order_by(DocumentFile.sort_order)
                )
            ).scalars().all()
            jobs = (
                await session.execute(
                    select(ProcessingJob).where(ProcessingJob.document_id == document_uuid).order_by(ProcessingJob.created_at)
                )
            ).scalars().all()
            ocr_results = (
                await session.execute(select(OcrResult).where(OcrResult.document_id == document_uuid))
            ).scalars().all()
            extractions = (
                await session.execute(select(DocumentExtraction).where(DocumentExtraction.document_id == document_uuid))
            ).scalars().all()

        return {
            "document_count": len(document_count),
            "file_paths": [file.storage_path for file in files],
            "job_count": len(jobs),
            "ocr_count": len(ocr_results),
            "ocr_texts": [result.normalized_text for result in ocr_results],
            "extraction_count": len(extractions),
        }

    return asyncio.run(read_snapshot())


def test_documents_require_authentication():
    with TestClient(app) as client:
        response = client.get("/api/documents")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "http_401"


def test_authenticated_user_gets_empty_document_list_for_now():
    email = f"docs-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        response = client.get("/api/documents")

    assert response.status_code == 200
    assert response.json() == []


def test_authenticated_user_can_upload_png_document():
    email = f"upload-png-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        response = client.post(
            "/api/documents",
            files={"file": ("receipt.jpg", b"\x89PNG\r\n\x1a\nfake-png-body", "image/jpeg")},
        )
        assert response.status_code == 201, response.text
        document = response.json()
        assert document["filename"] == "receipt.jpg"
        assert document["mime_type"] == "image/png"
        assert document["status"] == "uploaded"

        list_response = client.get("/api/documents")
        assert list_response.status_code == 200, list_response.text
        assert list_response.json()[0]["id"] == document["id"]

        jobs_response = client.get(f"/api/documents/{document['id']}/jobs")
        files_response = client.get(f"/api/documents/{document['id']}/files")
        assert jobs_response.status_code == 200, jobs_response.text
        assert jobs_response.json()[0]["kind"] == "ocr"
        assert jobs_response.json()[0]["status"] == "queued"
        assert files_response.status_code == 200, files_response.text
        assert files_response.json()[0]["filename"] == "receipt.jpg"
        assert files_response.json()[0]["mime_type"] == "image/png"


def test_user_can_add_and_delete_document_files():
    email = f"multi-file-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        upload_response = client.post(
            "/api/documents",
            files={"file": ("receipt-1.png", b"\x89PNG\r\n\x1a\nfirst", "image/png")},
        )
        assert upload_response.status_code == 201, upload_response.text
        document_id = upload_response.json()["id"]

        add_response = client.post(
            f"/api/documents/{document_id}/files",
            files={"file": ("receipt-2.jpg", b"\xff\xd8\xff\xe0second", "image/jpeg")},
        )
        files_response = client.get(f"/api/documents/{document_id}/files")
        assert add_response.status_code == 201, add_response.text
        assert files_response.status_code == 200, files_response.text
        assert [item["filename"] for item in files_response.json()] == ["receipt-1.png", "receipt-2.jpg"]

        first_file_id = files_response.json()[0]["id"]
        delete_response = client.delete(f"/api/documents/{document_id}/files/{first_file_id}")
        remaining_files_response = client.get(f"/api/documents/{document_id}/files")

        assert delete_response.status_code == 204, delete_response.text
        assert [item["filename"] for item in remaining_files_response.json()] == ["receipt-2.jpg"]

        last_file_id = remaining_files_response.json()[0]["id"]
        last_delete_response = client.delete(f"/api/documents/{document_id}/files/{last_file_id}")

        assert last_delete_response.status_code == 400
        assert last_delete_response.json()["detail"] == "Cannot delete the last file. Delete the whole document instead."


def test_user_can_delete_whole_document():
    email = f"delete-doc-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        upload_response = client.post(
            "/api/documents",
            files={"file": ("receipt.png", b"\x89PNG\r\n\x1a\nfake-png-body", "image/png")},
        )
        assert upload_response.status_code == 201, upload_response.text
        document_id = upload_response.json()["id"]

        delete_response = client.delete(f"/api/documents/{document_id}")
        read_response = client.get(f"/api/documents/{document_id}")
        files_response = client.get(f"/api/documents/{document_id}/files")

    assert delete_response.status_code == 204, delete_response.text
    assert read_response.status_code == 404
    assert files_response.status_code == 404


def test_authenticated_user_can_upload_jpeg_and_pdf_documents():
    email = f"upload-types-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        jpeg_response = client.post(
            "/api/documents",
            files={"file": ("receipt.jpeg", b"\xff\xd8\xff\xe0fake-jpeg-body", "image/jpeg")},
        )
        pdf_response = client.post(
            "/api/documents",
            files={"file": ("invoice.pdf", b"%PDF-1.4\nfake-pdf-body", "application/pdf")},
        )

    assert jpeg_response.status_code == 201, jpeg_response.text
    assert jpeg_response.json()["mime_type"] == "image/jpeg"
    assert pdf_response.status_code == 201, pdf_response.text
    assert pdf_response.json()["mime_type"] == "application/pdf"


def test_upload_rejects_text_file_renamed_to_jpg():
    email = f"fake-jpg-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        response = client.post(
            "/api/documents",
            files={"file": ("receipt.jpg", b"this is not an image", "image/jpeg")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported file type. Upload PNG, JPEG or PDF."


def test_upload_rejects_empty_file():
    email = f"empty-file-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        response = client.post(
            "/api/documents",
            files={"file": ("empty.png", b"", "image/png")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "File is empty"


def test_upload_rejects_too_large_file():
    email = f"large-file-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        response = client.post(
            "/api/documents",
            files={"file": ("large.png", b"\x89PNG\r\n\x1a\n" + (b"x" * (10 * 1024 * 1024)), "image/png")},
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "File is too large"


def test_user_cannot_read_another_users_document():
    first_email = f"doc-owner-{uuid.uuid4()}@example.com"
    second_email = f"doc-intruder-{uuid.uuid4()}@example.com"

    with TestClient(app) as owner:
        _register_and_login(owner, first_email)
        upload_response = owner.post(
            "/api/documents",
            files={"file": ("receipt.png", b"\x89PNG\r\n\x1a\nfake-png-body", "image/png")},
        )
        assert upload_response.status_code == 201, upload_response.text
        document_id = upload_response.json()["id"]

    with TestClient(app) as intruder:
        _register_and_login(intruder, second_email)
        read_response = intruder.get(f"/api/documents/{document_id}")
        list_response = intruder.get("/api/documents")

    assert read_response.status_code == 404
    assert list_response.status_code == 200
    assert list_response.json() == []


def test_user_cannot_mutate_another_users_document_files_jobs_or_extraction():
    first_email = f"doc-owner-actions-{uuid.uuid4()}@example.com"
    second_email = f"doc-intruder-actions-{uuid.uuid4()}@example.com"

    with TestClient(app) as owner:
        _register_and_login(owner, first_email)
        upload_response = owner.post(
            "/api/documents",
            files={"file": ("receipt.png", b"\x89PNG\r\n\x1a\nfake-png-body", "image/png")},
        )
        assert upload_response.status_code == 201, upload_response.text
        document_id = upload_response.json()["id"]
        files_response = owner.get(f"/api/documents/{document_id}/files")
        assert files_response.status_code == 200, files_response.text
        file_id = files_response.json()[0]["id"]

    with TestClient(app) as intruder:
        _register_and_login(intruder, second_email)
        add_file_response = intruder.post(
            f"/api/documents/{document_id}/files",
            files={"file": ("intruder.png", b"\x89PNG\r\n\x1a\nintruder", "image/png")},
        )
        delete_file_response = intruder.delete(f"/api/documents/{document_id}/files/{file_id}")
        jobs_response = intruder.get(f"/api/documents/{document_id}/jobs")
        extraction_response = intruder.get(f"/api/documents/{document_id}/extraction")
        update_extraction_response = intruder.put(
            f"/api/documents/{document_id}/extraction",
            json={"structured_json": {"summary": "Should not be saved"}},
        )
        run_extraction_response = intruder.post(f"/api/documents/{document_id}/extraction/run")

    assert add_file_response.status_code == 404
    assert delete_file_response.status_code == 404
    assert jobs_response.status_code == 404
    assert extraction_response.status_code == 404
    assert update_extraction_response.status_code == 404
    assert run_extraction_response.status_code == 404


def test_user_can_run_ocr_and_read_result(monkeypatch):
    monkeypatch.setattr("app.services.ocr.settings.ocr_engine", "tesseract")

    def fake_extract(self, document):
        return ExtractedText(
            raw_text="Datum: 12.05.2026\nCelkem 123,45 Kc",
            normalized_text="Datum: 12.05.2026\nCelkem 123,45 Kc",
            rag_text="Soubor: receipt.png\nKandidati datumu: 12.05.2026\nKandidati castek: 123,45\nOCR text:\nDatum: 12.05.2026\nCelkem 123,45 Kc",
            metadata_json={"dates": ["12.05.2026"], "amounts": ["123,45"], "line_count": 2},
            language="ces+eng",
            page_count=1,
            engine="fake-tesseract",
        )

    monkeypatch.setattr("app.services.ocr.TesseractOcrEngine.extract", fake_extract)
    email = f"ocr-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        upload_response = client.post(
            "/api/documents",
            files={"file": ("receipt.png", b"\x89PNG\r\n\x1a\nfake-png-body", "image/png")},
        )
        assert upload_response.status_code == 201, upload_response.text
        document_id = upload_response.json()["id"]

        run_response = client.post(f"/api/documents/{document_id}/ocr/run")
        assert run_response.status_code == 200, run_response.text
        assert run_response.json()["status"] == "succeeded"

        document_response = client.get(f"/api/documents/{document_id}")
        ocr_response = client.get(f"/api/documents/{document_id}/ocr")

    assert document_response.status_code == 200
    assert document_response.json()["status"] == "processed"
    assert ocr_response.status_code == 200
    assert ocr_response.json()["normalized_text"] == "Datum: 12.05.2026\nCelkem 123,45 Kc"
    assert "Kandidati datumu: 12.05.2026" in ocr_response.json()["rag_text"]
    assert ocr_response.json()["metadata_json"]["amounts"] == ["123,45"]
    assert ocr_response.json()["engine"] == "fake-tesseract"


def test_ocr_receives_all_files_for_one_document(monkeypatch):
    monkeypatch.setattr("app.services.ocr.settings.ocr_engine", "tesseract")

    def fake_extract(self, document):
        assert [document_file.filename for document_file in document.files] == ["receipt-1.png", "receipt-2.png"]
        return ExtractedText(
            raw_text="Cast 1\nCast 2",
            normalized_text="Cast 1\nCast 2",
            rag_text="OCR text:\nCast 1\nCast 2",
            metadata_json={"dates": [], "amounts": [], "line_count": 2, "file_count": 2},
            language="ces+eng",
            page_count=2,
            engine="fake-tesseract",
        )

    monkeypatch.setattr("app.services.ocr.TesseractOcrEngine.extract", fake_extract)
    email = f"ocr-multi-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        upload_response = client.post(
            "/api/documents",
            files={"file": ("receipt-1.png", b"\x89PNG\r\n\x1a\nfirst", "image/png")},
        )
        assert upload_response.status_code == 201, upload_response.text
        document_id = upload_response.json()["id"]
        add_response = client.post(
            f"/api/documents/{document_id}/files",
            files={"file": ("receipt-2.png", b"\x89PNG\r\n\x1a\nsecond", "image/png")},
        )
        assert add_response.status_code == 201, add_response.text

        run_response = client.post(f"/api/documents/{document_id}/ocr/run")
        ocr_response = client.get(f"/api/documents/{document_id}/ocr")

    assert run_response.status_code == 200
    assert run_response.json()["status"] == "succeeded"
    assert ocr_response.json()["page_count"] == 2
    assert ocr_response.json()["metadata_json"]["file_count"] == 2


def test_user_can_run_llm_extraction_after_ocr(monkeypatch):
    monkeypatch.setattr("app.services.extraction.settings.extraction_mode", "text_only")
    monkeypatch.setattr("app.services.ocr.settings.ocr_engine", "tesseract")

    def fake_extract(self, document):
        return ExtractedText(
            raw_text="LIDL PLZEN\nDatum 25.05.2026\nCelkem 24,00 Kc",
            normalized_text="LIDL PLZEN\nDatum 25.05.2026\nCelkem 24,00 Kc",
            rag_text="OCR text:\nLIDL PLZEN\nDatum 25.05.2026\nCelkem 24,00 Kc",
            metadata_json={"dates": ["25.05.2026"], "amounts": ["24,00"], "line_count": 3},
            language="ces+eng",
            page_count=1,
            engine="fake-tesseract",
        )

    async def fake_extract_json(self, prompt, model=None):
        assert "LIDL PLZEN" in prompt
        assert model == "llama3.1:8b"
        return """
        {
          "document_type": "receipt",
          "issue_date": "2026-05-25",
          "taxable_supply_date": null,
          "due_date": null,
          "invoice_number": null,
          "delivery_note_number": null,
          "merchant": {"name": "Lidl", "ico": null, "dic": null, "registered_address": {"raw": null, "street": null, "city": null, "postal_code": null, "country": null}, "store_address": {"raw": "Namesti republiky Plzen", "street": null, "city": "Plzen", "postal_code": null, "country": "CZ"}},
          "order": {"order_number": null, "order_date": null},
          "payment": {"total": {"amount": 24.0, "raw": "24,00 Kc"}, "payment_method": null, "currency": "CZK", "bank_account": {"account_number": null, "iban": null, "swift": null, "bank_name": null}, "variable_symbol": null, "constant_symbol": null},
          "buyer": {"name": null, "ico": null, "dic": null, "billing_address": {"raw": null, "street": null, "city": null, "postal_code": null, "country": null}, "delivery_address": {"raw": null, "street": null, "city": null, "postal_code": null, "country": null}},
          "items": [{"name": "Rohlik", "quantity": 2, "unit": "ks", "unit_price": null, "total_price": 24.0, "raw": "Rohlik 24,00", "tax": {"vat_amount": null, "vat_rate": null}}],
          "tax_summary": [],
          "summary": "Nakup v Lidl v Plzni dne 25.05.2026 za 24 Kc.",
          "confidence": {"issue_date": 0.9, "merchant": 0.9, "buyer": 0.0, "payment": 0.95, "items": 0.5},
          "needs_review": true,
          "evidence": {"issue_date": "25.05.2026", "merchant": "LIDL", "buyer": null, "payment": "24,00 Kc", "total": "24,00 Kc", "order_number": null}
        }
        """

    monkeypatch.setattr("app.services.ocr.TesseractOcrEngine.extract", fake_extract)
    monkeypatch.setattr("app.services.ollama.OllamaClient.extract_json", fake_extract_json)
    email = f"extract-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        upload_response = client.post(
            "/api/documents",
            files={"file": ("receipt.png", b"\x89PNG\r\n\x1a\nfake-png-body", "image/png")},
        )
        assert upload_response.status_code == 201, upload_response.text
        document_id = upload_response.json()["id"]

        settings_response = client.put("/api/settings", json={"ocr_processing_model": "llama3.1:8b"})
        assert settings_response.status_code == 200, settings_response.text
        assert settings_response.json()["ocr_processing_model"] == "llama3.1:8b"

        ocr_run_response = client.post(f"/api/documents/{document_id}/ocr/run")
        extraction_run_response = client.post(f"/api/documents/{document_id}/extraction/run")
        extraction_response = client.get(f"/api/documents/{document_id}/extraction")
        ocr_response = client.get(f"/api/documents/{document_id}/ocr")

    assert ocr_run_response.status_code == 200
    assert extraction_run_response.status_code == 200
    assert extraction_run_response.json()["status"] == "succeeded"
    extraction = extraction_response.json()
    assert extraction["structured_json"]["merchant"]["name"] == "Lidl"
    assert extraction["structured_json"]["payment"]["total"]["amount"] == 24.0
    assert extraction["summary"] == "Nakup v Lidl v Plzni dne 25.05.2026 za 24 Kc."
    assert extraction["review_status"] == "draft"
    assert "Popis: Nakup v Lidl" in ocr_response.json()["rag_text"]


def test_user_can_save_extraction_edits_and_reindex_rag(monkeypatch):
    monkeypatch.setattr("app.services.extraction.settings.extraction_mode", "text_only")
    monkeypatch.setattr("app.services.ocr.settings.ocr_engine", "tesseract")
    indexed = {}

    def fake_extract(self, document):
        return ExtractedText(
            raw_text="BAUHAUS\nDVOJNIPL PLAST 1/2\nCelkem 55,00 Kc",
            normalized_text="BAUHAUS\nDVOJNIPL PLAST 1/2\nCelkem 55,00 Kc",
            rag_text="OCR text:\nBAUHAUS\nDVOJNIPL PLAST 1/2\nCelkem 55,00 Kc",
            metadata_json={"dates": [], "amounts": ["55,00"], "line_count": 3},
            language="ces+eng",
            page_count=1,
            engine="fake-tesseract",
        )

    async def fake_extract_json(self, prompt, model=None):
        return """
        {
          "document_type": "receipt",
          "issue_date": "2026-05-05",
          "taxable_supply_date": null,
          "due_date": null,
          "invoice_number": null,
          "delivery_note_number": null,
          "merchant": {"name": "BAUHAUS", "ico": null, "dic": null, "registered_address": {"raw": null, "street": null, "city": null, "postal_code": null, "country": null}, "store_address": {"raw": "Plzen", "street": null, "city": "Plzen", "postal_code": null, "country": "CZ"}},
          "order": {"order_number": null, "order_date": null},
          "payment": {"total": {"amount": 55.0, "raw": "55,00 Kc"}, "payment_method": null, "currency": "CZK", "bank_account": {"account_number": null, "iban": null, "swift": null, "bank_name": null}, "variable_symbol": null, "constant_symbol": null},
          "buyer": {"name": null, "ico": null, "dic": null, "billing_address": {"raw": null, "street": null, "city": null, "postal_code": null, "country": null}, "delivery_address": {"raw": null, "street": null, "city": null, "postal_code": null, "country": null}},
          "items": [{"name": "DVOJNIPL PLAST 1/2", "quantity": 1, "unit": "ks", "unit_price": 55.0, "total_price": 55.0, "raw": "DVOJNIPL PLAST 1/2", "tax": {"vat_amount": null, "vat_rate": null}}],
          "tax_summary": [],
          "summary": "Nakup v BAUHAUS za 55 Kc.",
          "confidence": {},
          "needs_review": true,
          "evidence": {}
        }
        """

    async def fake_index(session, document, rag_text, extraction, client=None):
        indexed["rag_text"] = rag_text
        indexed["extraction"] = extraction
        return True

    monkeypatch.setattr("app.services.ocr.TesseractOcrEngine.extract", fake_extract)
    monkeypatch.setattr("app.services.ollama.OllamaClient.extract_json", fake_extract_json)
    monkeypatch.setattr("app.api.documents.index_document_rag_text", fake_index)
    email = f"save-extraction-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        upload_response = client.post(
            "/api/documents",
            files={"file": ("receipt.png", b"\x89PNG\r\n\x1a\nfake-png-body", "image/png")},
        )
        document_id = upload_response.json()["id"]
        client.post(f"/api/documents/{document_id}/ocr/run")
        client.post(f"/api/documents/{document_id}/extraction/run")

        update_response = client.put(
            f"/api/documents/{document_id}/extraction",
            json={
                "structured_json": {
                    "document_type": "receipt",
                    "issue_date": "2026-05-05",
                    "merchant": {"name": "BAUHAUS"},
                    "payment": {"total": {"amount": 55.0, "raw": "55,00 Kc"}, "currency": "CZK"},
                    "buyer": {},
                    "order": {},
                    "items": [
                        {
                            "name": "DVOJNIPL PLAST 1/2",
                            "user_label": "Plastovy obrubnik",
                            "user_note": "Betonovy zahradni obrubnik kolem zahonu",
                            "total_price": 55.0,
                        }
                    ],
                    "tax_summary": [],
                    "summary": "Nakup plastoveho obrubniku v BAUHAUS dne 05.05.2026 za 55 Kc.",
                }
            },
        )
        ocr_response = client.get(f"/api/documents/{document_id}/ocr")

    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["review_status"] == "approved"
    assert update_response.json()["structured_json"]["items"][0]["name"] == "DVOJNIPL PLAST 1/2"
    assert update_response.json()["structured_json"]["items"][0]["user_label"] == "Plastovy obrubnik"
    assert "DVOJNIPL PLAST 1/2" in ocr_response.json()["rag_text"]
    assert "Plastovy obrubnik" in ocr_response.json()["rag_text"]
    assert "Betonovy zahradni obrubnik" in ocr_response.json()["rag_text"]
    assert "Plastovy obrubnik" in indexed["rag_text"]


def test_adding_document_file_invalidates_processed_outputs_and_queues_ocr(monkeypatch):
    monkeypatch.setattr("app.services.extraction.settings.extraction_mode", "text_only")
    monkeypatch.setattr("app.services.ocr.settings.ocr_engine", "tesseract")
    cleared_chunk_ids = []

    def fake_extract(self, document):
        return _fake_extracted_text("Puvodni OCR\nCelkem 123,00 Kc")

    async def fake_extract_json(self, prompt, model=None):
        return _minimal_extraction_json("Puvodni strukturovany doklad.")

    async def fake_delete_chunks(session, document_id):
        cleared_chunk_ids.append(str(document_id))

    monkeypatch.setattr("app.services.ocr.TesseractOcrEngine.extract", fake_extract)
    monkeypatch.setattr("app.services.ollama.OllamaClient.extract_json", fake_extract_json)
    monkeypatch.setattr("app.api.documents.delete_document_chunks", fake_delete_chunks)
    email = f"invalidate-file-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        upload_response = client.post(
            "/api/documents",
            files={"file": ("receipt-1.png", b"\x89PNG\r\n\x1a\nfirst", "image/png")},
        )
        document_id = upload_response.json()["id"]
        ocr_run_response = client.post(f"/api/documents/{document_id}/ocr/run")
        extraction_run_response = client.post(f"/api/documents/{document_id}/extraction/run")
        assert ocr_run_response.status_code == 200, ocr_run_response.text
        assert extraction_run_response.status_code == 200, extraction_run_response.text
        assert client.get(f"/api/documents/{document_id}/ocr").status_code == 200
        assert client.get(f"/api/documents/{document_id}/extraction").status_code == 200

        add_file_response = client.post(
            f"/api/documents/{document_id}/files",
            files={"file": ("receipt-2.png", b"\x89PNG\r\n\x1a\nsecond", "image/png")},
        )
        document_response = client.get(f"/api/documents/{document_id}")
        ocr_response = client.get(f"/api/documents/{document_id}/ocr")
        extraction_response = client.get(f"/api/documents/{document_id}/extraction")
        jobs_response = client.get(f"/api/documents/{document_id}/jobs")

    assert add_file_response.status_code == 201, add_file_response.text
    assert document_response.json()["status"] == "uploaded"
    assert ocr_response.status_code == 404
    assert extraction_response.status_code == 404
    new_ocr_jobs = [
        job
        for job in jobs_response.json()
        if job["kind"] == "ocr" and job["status"] == "queued" and job["payload"].get("action") == "file_added"
    ]
    assert len(new_ocr_jobs) == 1
    assert str(document_id) in cleared_chunk_ids


def test_delete_document_removes_related_state_and_stored_files(monkeypatch, tmp_path):
    monkeypatch.setattr("app.core.config.settings.document_storage_dir", str(tmp_path))
    monkeypatch.setattr("app.services.extraction.settings.extraction_mode", "text_only")
    monkeypatch.setattr("app.services.ocr.settings.ocr_engine", "tesseract")
    cleared_chunk_ids = []

    def fake_extract(self, document):
        return _fake_extracted_text("Doklad ke smazani\nCelkem 123,00 Kc")

    async def fake_extract_json(self, prompt, model=None):
        return _minimal_extraction_json("Doklad ke smazani.")

    async def fake_delete_chunks(session, document_id):
        cleared_chunk_ids.append(str(document_id))

    monkeypatch.setattr("app.services.ocr.TesseractOcrEngine.extract", fake_extract)
    monkeypatch.setattr("app.services.ollama.OllamaClient.extract_json", fake_extract_json)
    monkeypatch.setattr("app.api.documents.delete_document_chunks", fake_delete_chunks)
    email = f"delete-integrity-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        upload_response = client.post(
            "/api/documents",
            files={"file": ("receipt.png", b"\x89PNG\r\n\x1a\nfake-png-body", "image/png")},
        )
        document_id = upload_response.json()["id"]
        client.post(f"/api/documents/{document_id}/ocr/run")
        client.post(f"/api/documents/{document_id}/extraction/run")

        before_delete = _document_integrity_snapshot(document_id)
        stored_paths = [Path(path) for path in before_delete["file_paths"]]
        stored_paths_existed_before_delete = bool(stored_paths) and all(path.exists() for path in stored_paths)
        delete_response = client.delete(f"/api/documents/{document_id}")
        read_response = client.get(f"/api/documents/{document_id}")
        jobs_response = client.get(f"/api/documents/{document_id}/jobs")

    assert before_delete["document_count"] == 1
    assert before_delete["job_count"] >= 2
    assert before_delete["ocr_count"] == 1
    assert before_delete["extraction_count"] == 1
    assert stored_paths
    assert stored_paths_existed_before_delete

    assert delete_response.status_code == 204, delete_response.text
    assert read_response.status_code == 404
    assert jobs_response.status_code == 404
    after_delete = _document_integrity_snapshot(document_id)
    assert after_delete == {
        "document_count": 0,
        "file_paths": [],
        "job_count": 0,
        "ocr_count": 0,
        "ocr_texts": [],
        "extraction_count": 0,
    }
    assert all(not path.exists() for path in stored_paths)
    assert str(document_id) in cleared_chunk_ids


def test_rerunning_ocr_reuses_single_ocr_result(monkeypatch):
    monkeypatch.setattr("app.services.ocr.settings.ocr_engine", "tesseract")
    calls = {"count": 0}

    def fake_extract(self, document):
        calls["count"] += 1
        return _fake_extracted_text(f"OCR run {calls['count']}\nCelkem 123,00 Kc")

    monkeypatch.setattr("app.services.ocr.TesseractOcrEngine.extract", fake_extract)
    email = f"rerun-ocr-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        upload_response = client.post(
            "/api/documents",
            files={"file": ("receipt.png", b"\x89PNG\r\n\x1a\nfake-png-body", "image/png")},
        )
        document_id = upload_response.json()["id"]
        first_run_response = client.post(f"/api/documents/{document_id}/ocr/run")
        second_run_response = client.post(f"/api/documents/{document_id}/ocr/run")

    assert first_run_response.status_code == 200, first_run_response.text
    assert second_run_response.status_code == 200, second_run_response.text
    assert first_run_response.json()["payload"]["ocr_result_id"] == second_run_response.json()["payload"]["ocr_result_id"]
    snapshot = _document_integrity_snapshot(document_id)
    assert snapshot["ocr_count"] == 1
    assert snapshot["ocr_texts"] == ["OCR run 2\nCelkem 123,00 Kc"]


def test_llm_extraction_uses_hybrid_images_when_enabled(monkeypatch):
    monkeypatch.setattr("app.services.extraction.settings.extraction_mode", "vision_hybrid")
    monkeypatch.setattr("app.services.ocr.settings.ocr_engine", "tesseract")
    monkeypatch.setattr("app.services.extraction.build_extraction_image_payloads", lambda document: ["base64-image"])
    captured = {}

    def fake_extract(self, document):
        return ExtractedText(
            raw_text="HECHT MOTORS\nCislo objednavky POB26-058499\nCelkem 4 990,00 CZK",
            normalized_text="HECHT MOTORS\nCislo objednavky POB26-058499\nCelkem 4 990,00 CZK",
            rag_text="OCR text:\nHECHT MOTORS\nCelkem 4 990,00 CZK",
            metadata_json={"dates": [], "amounts": ["4 990,00"], "line_count": 3},
            language="ces+eng",
            page_count=1,
            engine="fake-tesseract",
        )

    async def fake_extract_json_with_images(self, prompt, images, model=None):
        captured["prompt"] = prompt
        captured["images"] = images
        captured["model"] = model
        return """
        {
          "document_type": "invoice",
          "issue_date": null,
          "taxable_supply_date": null,
          "due_date": null,
          "invoice_number": null,
          "delivery_note_number": null,
          "merchant": {"name": "HECHT MOTORS", "ico": null, "dic": null, "registered_address": {"raw": null, "street": null, "city": null, "postal_code": null, "country": null}, "store_address": {"raw": null, "street": null, "city": null, "postal_code": null, "country": null}},
          "order": {"order_number": "POB26-058499", "order_date": null},
          "payment": {"total": {"amount": 4990.0, "raw": "4 990,00 CZK"}, "payment_method": null, "currency": "CZK", "bank_account": {"account_number": null, "iban": null, "swift": null, "bank_name": null}, "variable_symbol": null, "constant_symbol": null},
          "buyer": {"name": null, "ico": null, "dic": null, "billing_address": {"raw": null, "street": null, "city": null, "postal_code": null, "country": null}, "delivery_address": {"raw": null, "street": null, "city": null, "postal_code": null, "country": null}},
          "items": [],
          "tax_summary": [],
          "summary": "Faktura HECHT MOTORS za 4 990,00 CZK.",
          "confidence": {"issue_date": 0, "merchant": 0.9, "buyer": 0.2, "payment": 0.95, "items": 0.1},
          "needs_review": true,
          "evidence": {"issue_date": null, "merchant": "HECHT MOTORS", "buyer": null, "payment": "4 990,00 CZK", "total": "4 990,00 CZK", "order_number": "POB26-058499"}
        }
        """

    monkeypatch.setattr("app.services.ocr.TesseractOcrEngine.extract", fake_extract)
    monkeypatch.setattr("app.services.ollama.OllamaClient.extract_json_with_images", fake_extract_json_with_images)
    email = f"hybrid-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        upload_response = client.post(
            "/api/documents",
            files={"file": ("invoice.png", b"\x89PNG\r\n\x1a\nfake-png-body", "image/png")},
        )
        document_id = upload_response.json()["id"]
        ocr_run_response = client.post(f"/api/documents/{document_id}/ocr/run")
        extraction_run_response = client.post(f"/api/documents/{document_id}/extraction/run")

    assert ocr_run_response.status_code == 200
    assert extraction_run_response.status_code == 200
    assert extraction_run_response.json()["status"] == "succeeded"
    assert captured["images"] == ["base64-image"]
    assert "OCR text: pouzij ho jako primarni zdroj" in captured["prompt"]
    assert "HECHT MOTORS" in captured["prompt"]
    assert extraction_run_response.json()["payload"]["extraction_mode"] == "vision_hybrid"
    assert extraction_run_response.json()["payload"]["image_count"] == 1


def test_invoice_extraction_schema_distinguishes_address_roles():
    from app.services.extraction import build_structured_rag_text, parse_extraction_response

    response = """
    {
      "document_type": "invoice",
      "date": "2026-04-30",
      "issue_date": "2026-04-30",
      "taxable_supply_date": "2026-04-30",
      "due_date": "2026-05-14",
      "order_number": "POB26-058499",
      "invoice_number": "261731145",
      "variable_symbol": "261731145",
      "constant_symbol": "0008",
      "delivery_note_number": "RDL26-148-001141",
      "payment_method": "Hotově",
      "merchant": {"name": "HECHT MOTORS s.r.o.", "ico": "61461661", "dic": "CZ61461661"},
      "seller_address": {"raw": "Mototechny 131, 251 62 Tehovec", "street": "Mototechny 131", "city": "Tehovec", "postal_code": "251 62", "country": "CZ"},
      "registered_office_address": {"raw": "Mototechny 131, 251 62 Tehovec", "street": "Mototechny 131", "city": "Tehovec", "postal_code": "251 62", "country": "CZ"},
      "business_premises_address": {"raw": null, "street": null, "city": null, "postal_code": null, "country": null},
      "buyer": {"name": "Václav Lepič", "ico": null, "dic": null},
      "billing_address": {"raw": "Na Chrastech 777, 33027 Vejprnice", "street": "Na Chrastech 777", "city": "Vejprnice", "postal_code": "33027", "country": "CZ"},
      "delivery_address": {"raw": null, "street": null, "city": null, "postal_code": null, "country": null},
      "place": {"raw": null, "street": null, "city": null, "postal_code": null, "country": null, "role": null},
      "bank_account": {"account_number": "3483490/0300", "iban": "CZ25 0300 0000 0000 0348 3490", "swift": "CEKOCZPP", "bank_name": "Československá obchodní banka"},
      "payment": {"total": {"amount": 4990.0, "raw": "4 990,00 CZK"}, "payment_method": "HotovÄ›", "currency": "CZK", "bank_account": {"account_number": "3483490/0300", "iban": "CZ25 0300 0000 0000 0348 3490", "swift": "CEKOCZPP", "bank_name": "ÄŚeskoslovenskĂˇ obchodnĂ­ banka"}, "variable_symbol": "261731145", "constant_symbol": "0008"},
      "currency": "CZK",
      "total": {"amount": 4990.0, "raw": "4 990,00 CZK"},
      "tax": {"vat_amount": 866.03, "vat_rate": 21},
      "items": [{"name": "Robotická sekačka HECHT5604", "quantity": 1, "unit": "KS", "unit_price": 4123.97, "total_price": 4990.0, "raw": "HECHT5604 Robotická sekačka"}],
      "summary": "Faktura HECHT MOTORS za robotickou sekačku HECHT5604 vystavená 30.04.2026, celkem 4 990 Kč, úhrada hotově.",
      "confidence": {"date": 1, "merchant": 1, "addresses": 0.9, "total": 1, "items": 0.9},
      "needs_review": false,
      "evidence": {"date": "30.04.2026", "merchant": "HECHT MOTORS s.r.o.", "addresses": "Mototechny 131 / Na Chrastech 777", "total": "4 990,00 CZK", "order_number": "POB26-058499"}
    }
    """

    structured = parse_extraction_response(response)
    assert structured["place"]["raw"] is None
    assert structured["billing_address"]["city"] == "Vejprnice"
    assert structured["seller_address"]["city"] == "Tehovec"
    assert structured["order_number"] == "POB26-058499"

    class FakeDocument:
        filename = "invoice.jpg"

    class FakeOcr:
        normalized_text = "FAKTURA HECHT MOTORS"

    rag_text = build_structured_rag_text(FakeDocument(), FakeOcr(), structured)
    assert "Fakturacni adresa: Na Chrastech 777, 33027 Vejprnice" in rag_text
    assert "Misto nakupu/prodeje:" not in rag_text
    assert "Cislo objednavky: POB26-058499" in rag_text


def test_extraction_prompt_guards_nested_schema_and_payment_conflicts():
    from app.services.extraction import build_extraction_prompt

    class FakeDocument:
        filename = "invoice.jpg"
        mime_type = "image/jpeg"

    class FakeOcr:
        metadata_json = {}
        normalized_text = """
        Forma uhrady: Hotove
        Typ uhrady: Kreditni karta: 4990.00 CZK
        Dod. list(y) c./ze dne: RDL26-148-001141 / 30.04.2026
        Celkova castka k uhrade: 4 990,00 CZK
        """

    prompt = build_extraction_prompt(FakeDocument(), FakeOcr())

    assert "Vrat pouze klice uvedene ve schematu" in prompt
    assert "`merchant.bank_account` patri k dodavateli/prodejci" in prompt
    assert "Ruzne telefony nebo e-maily u sidla a provozovny nejsou rozpor" in prompt
    assert '"registered_contact": {"phone": "string|null", "email": "string|null"}' in prompt
    assert '"store_contact": {"phone": "string|null", "email": "string|null"}' in prompt
    assert "preferuj `Kreditni karta`" in prompt
    assert "Datum dodaciho listu" in prompt
    assert "`payment.total.raw` ma obsahovat i menu" in prompt


def test_user_can_update_document_processing_settings():
    email = f"settings-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        read_response = client.get("/api/settings")
        update_response = client.put("/api/settings", json={"ocr_processing_model": "mistral-small"})
        second_read_response = client.get("/api/settings")

    assert read_response.status_code == 200, read_response.text
    assert read_response.json()["ocr_processing_model"] is None
    assert read_response.json()["rag_source_strategy"] == "best_band"
    assert read_response.json()["rag_best_band"] == 0.08
    assert read_response.json()["rag_top_n"] == 2

    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["ocr_processing_model"] == "mistral-small"
    assert update_response.json()["rag_source_strategy"] == "best_band"
    assert second_read_response.json()["ocr_processing_model"] == "mistral-small"


def test_user_can_update_rag_source_settings():
    email = f"rag-settings-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        update_response = client.put(
            "/api/settings",
            json={
                "ocr_processing_model": None,
                "rag_source_strategy": "top_n",
                "rag_best_band": 0.2,
                "rag_top_n": 4,
            },
        )
        read_response = client.get("/api/settings")

    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["rag_source_strategy"] == "top_n"
    assert update_response.json()["rag_best_band"] == 0.2
    assert update_response.json()["rag_top_n"] == 4
    assert read_response.json()["rag_source_strategy"] == "top_n"


def test_ocr_failure_marks_document_failed(monkeypatch):
    monkeypatch.setattr("app.services.ocr.settings.ocr_engine", "tesseract")

    def fake_extract(self, document):
        raise ValueError("OCR returned empty text")

    monkeypatch.setattr("app.services.ocr.TesseractOcrEngine.extract", fake_extract)
    email = f"ocr-failed-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        upload_response = client.post(
            "/api/documents",
            files={"file": ("receipt.png", b"\x89PNG\r\n\x1a\nfake-png-body", "image/png")},
        )
        assert upload_response.status_code == 201, upload_response.text
        document_id = upload_response.json()["id"]

        run_response = client.post(f"/api/documents/{document_id}/ocr/run")
        jobs_response = client.get(f"/api/documents/{document_id}/jobs")
        document_response = client.get(f"/api/documents/{document_id}")
        ocr_response = client.get(f"/api/documents/{document_id}/ocr")

    assert run_response.status_code == 200
    assert run_response.json()["status"] == "failed"
    assert document_response.json()["status"] == "failed"
    assert jobs_response.json()[0]["error_message"] == "OCR returned empty text"
    assert ocr_response.status_code == 404


def test_unknown_document_returns_stable_404_shape():
    email = f"missing-doc-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        response = client.get(f"/api/documents/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"


def test_request_id_is_returned_to_client():
    request_id = str(uuid.uuid4())

    with TestClient(app) as client:
        response = client.get("/api/health", headers={"x-request-id": request_id})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == request_id


def test_ocr_text_normalization_prepares_rag_ready_text():
    raw_text = "\n\n  DATUM:   12.05.2026  \n***\nCELKEM      1 234,50 Kc\n\n"

    normalized = normalize_ocr_text(raw_text)
    metadata = build_ocr_metadata(normalized)

    assert normalized == "DATUM: 12.05.2026\nCELKEM 1 234,50 Kc"
    assert metadata["dates"] == ["12.05.2026"]
    assert metadata["amounts"] == ["1 234,50"]
    assert metadata["line_count"] == 2


def test_ocr_engine_factory_selects_configured_engine(monkeypatch):
    monkeypatch.setattr("app.services.ocr.settings.ocr_engine", "tesseract")
    assert isinstance(create_ocr_engine(), TesseractOcrEngine)

    monkeypatch.setattr("app.services.ocr.settings.ocr_engine", "easyocr")
    assert isinstance(create_ocr_engine(), EasyOcrEngine)

    monkeypatch.setattr("app.services.ocr.settings.ocr_engine", "ollama")
    assert isinstance(create_ocr_engine(), OllamaOcrEngine)


def test_ollama_ocr_engine_sends_image_to_configured_model(monkeypatch, tmp_path):
    image_path = tmp_path / "receipt.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-body")
    captured_payload = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "# Uctenka\nCelkem 123,45 Kc"}}

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json):
            captured_payload["url"] = url
            captured_payload["json"] = json
            captured_payload["timeout"] = self.kwargs["timeout"]
            return FakeResponse()

    monkeypatch.setattr("app.services.ocr.httpx.Client", FakeClient)
    monkeypatch.setattr("app.services.ocr.settings.ollama_base_url", "http://ollama:11434")
    monkeypatch.setattr("app.services.ocr.settings.ollama_ocr_model", "glm-ocr:latest")
    monkeypatch.setattr("app.services.ocr.settings.ollama_ocr_prompt", "Text Recognition:")
    monkeypatch.setattr("app.services.ocr.settings.ollama_ocr_timeout_seconds", 180.0)

    text = OllamaOcrEngine()._run_ollama_ocr(image_path)

    assert text == "# Uctenka\nCelkem 123,45 Kc"
    assert captured_payload["url"] == "http://ollama:11434/api/chat"
    assert captured_payload["timeout"] == 180.0
    assert captured_payload["json"]["model"] == "glm-ocr:latest"
    assert captured_payload["json"]["stream"] is False
    assert captured_payload["json"]["messages"][0]["content"] == "Text Recognition:"
    assert captured_payload["json"]["messages"][0]["images"]


def test_ollama_ocr_engine_records_model_in_result_metadata(monkeypatch, tmp_path):
    image_path = tmp_path / "receipt.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-body")

    class FakeDocument:
        id = uuid.uuid4()
        user_id = uuid.uuid4()
        filename = "receipt.png"
        mime_type = "image/png"
        storage_path = str(image_path)
        files = []

    monkeypatch.setattr("app.services.ocr.settings.ollama_ocr_model", "glm-ocr:latest")
    monkeypatch.setattr("app.services.ocr.settings.ollama_ocr_prompt", "Text Recognition:")
    monkeypatch.setattr("app.services.ocr.OllamaOcrEngine._run_ollama_ocr", lambda self, path: "Datum\nCelkem 123,45 Kc")

    extracted = OllamaOcrEngine().extract(FakeDocument())

    assert extracted.engine == "ollama:glm-ocr:latest"
    assert extracted.metadata_json["ollama_model"] == "glm-ocr:latest"
    assert extracted.metadata_json["ollama_prompt"] == "Text Recognition:"
