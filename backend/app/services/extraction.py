import json
import base64
import subprocess
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from PIL import Image, ImageOps

from app.core.config import settings
from app.models.document import Document, DocumentExtraction, DocumentFile, OcrResult
from app.models.job import JobKind, JobStatus, ProcessingJob
from app.models.settings import UserSettings
from app.services.ollama import OllamaClient
from app.services.inference_routing import get_role_server
from app.services.vector_store import index_document_rag_text


REQUIRED_KEYS = {"document_type", "merchant", "payment", "buyer", "items", "summary"}


def build_extraction_prompt(document: Document, ocr_result: OcrResult) -> str:
    return f"""
Z OCR textu a pripadnych prilozenych obrazku vytvor strukturovany JSON pro uctenku nebo fakturu.

Mas k dispozici dva zdroje pravdy:
- OCR text: pouzij ho jako primarni zdroj pro presny opis znaku, cisel, ICO, DIC, IBAN, VS, KS, datumu a castek.
- Obrazek dokladu: pouzij ho jako primarni zdroj pro layout, vztahy poli, tabulky, sloupce a rozliseni roli adres. A jen sekundarne jako zdroj informací.

Pokud se OCR text a obrazek lisi, nevymyslej. Zvol hodnotu, ktera dava smysl podle obou zdroju, sniz confidence a nastav needs_review=true.
Pokud OCR text obsahuje preklep, ale obrazek jasne ukazuje spravnou hodnotu, muzes hodnotu opravit a uved ji v evidence.

Rozlisuj role adres.
Pokud hodnota neni jasna, pouzij null. Nevymyslej chybejici hodnoty.
Vrat pouze klice uvedene ve schematu. Pro e-mail pouzij klic `email`, ne `e-mail`.

Pravidla pro sporne hodnoty:
- `merchant.bank_account` patri k dodavateli/prodejci a muze byt vyplnen z faktury. `payment.bank_account` muze obsahovat stejny ucet, pokud je to ucet urceny k uhrade.
- `payment.payment_method` ma popisovat skutecnou platbu. Pokud druhy doklad nebo pokladni cast obsahuje `Typ uhrady: Kreditni karta`, preferuj `Kreditni karta` pred planovanou/formalni hodnotou z faktury jako `Hotove`.
- Pokud jsou v dokumentu dve ruzne platebni metody, vyber skutecne provedenou platbu, nastav `needs_review=true` a popis rozpor v `evidence.payment`.
- Ruzne telefony nebo e-maily u sidla a provozovny nejsou rozpor. Kontakt ze sidla firmy dej do `merchant.registered_contact`, kontakt z provozovny/prodejny dej do `merchant.store_contact`.
- `order.order_date` vypln jen pokud je explicitne oznaceno jako datum objednavky. Datum dodaciho listu, vystaveni faktury nebo zdanitelneho plneni neni datum objednavky.
- `due_date` vypln jen z pole `Datum splatnosti`; pokud ho v OCR textu ani obrazu jasne nevidis, pouzij null.
- `items[].raw`, `payment.total.raw` a `tax_summary[].raw` vypln presnym textem z OCR, pokud je dostupny. `payment.total.raw` ma obsahovat i menu, napr. `4 990,00 CZK`.
- `items[].user_label` a `items[].user_note` negeneruj. Jsou vyhradne pro pozdejsi rucni pojmenovani uzivatelem, proto je v AI vystupu neuvadej.
- Confidence `1` pouzij jen pro hodnoty primo dolozene v OCR textu nebo jasne citelne v obrazu. Pri rozporu nebo opravach OCR nastav max `0.8`.

Vrat presne tento tvar:
{{
  "document_type": "receipt|invoice|unknown",
  "issue_date": "YYYY-MM-DD|null",
  "taxable_supply_date": "YYYY-MM-DD|null",
  "due_date": "YYYY-MM-DD|null",
  "invoice_number": "string|null",
  "delivery_note_number": "string|null",
  "merchant": {{
    "name": "string|null",
    "ico": "string|null",
    "dic": "string|null",
    "bank_account": {{"account_number": "string|null", "iban": "string|null", "swift": "string|null", "bank_name": "string|null"}},
    "registered_contact": {{"phone": "string|null", "email": "string|null"}},
    "store_contact": {{"phone": "string|null", "email": "string|null"}},
    "registered_address": {{"raw": "string|null", "street": "string|null", "city": "string|null", "postal_code": "string|null", "country": "CZ|null"}},
    "store_address": {{"raw": "string|null", "street": "string|null", "city": "string|null", "postal_code": "string|null", "country": "CZ|null"}}
  }},
  "order": {{
    "order_number": "string|null",
    "order_date": "YYYY-MM-DD|null"
  }},
  "payment": {{
    "total": {{"amount": number|null, "raw": "string|null"}},
    "payment_method": "string|null",
    "currency": "CZK|EUR|USD|unknown",
    "bank_account": {{"account_number": "string|null", "iban": "string|null", "swift": "string|null", "bank_name": "string|null"}},
    "variable_symbol": "string|null",
    "constant_symbol": "string|null"
  }},
  "buyer": {{
    "name": "string|null",
    "ico": "string|null",
    "dic": "string|null",
    "billing_address": {{"raw": "string|null", "street": "string|null", "city": "string|null", "postal_code": "string|null", "country": "CZ|null"}},
    "delivery_address": {{"raw": "string|null", "street": "string|null", "city": "string|null", "postal_code": "string|null", "country": "CZ|null"}}
  }},
  "items": [{{"name": "string", "quantity": number|null, "unit": "string|null", "unit_price": number|null, "total_price": number|null, "raw": "string|null", "tax": {{"vat_amount": number|null, "vat_rate": number|null}}}}],
  "tax_summary": [{{"vat_rate": number|null, "tax_base": number|null, "vat_amount": number|null, "total": number|null, "raw": "string|null"}}],
  "summary": "kratky cesky popisek vhodny pro vyhledavani. U faktury preferuj dodavatele, predmet, datum, celkovou castku a zpusob uhrady; neprezentuj fakturacni adresu jako misto nakupu.",
  "confidence": {{"issue_date": number, "merchant": number, "buyer": number, "payment": number, "items": number}},
  "needs_review": true,
  "evidence": {{"issue_date": "string|null", "merchant": "string|null", "merchant_contacts": "string|null", "buyer": "string|null", "payment": "string|null", "total": "string|null", "order_number": "string|null"}}
}}

Soubor: {document.filename}
MIME: {document.mime_type}
OCR metadata: {json.dumps(ocr_result.metadata_json, ensure_ascii=False)}
OCR text:
{ocr_result.normalized_text}
""".strip()


def _prepare_image_payload(path: Path, tmp_dir: Path) -> str:
    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    image.thumbnail((settings.extraction_image_max_side, settings.extraction_image_max_side))
    prepared_path = tmp_dir / f"{path.stem}.jpg"
    image.save(prepared_path, format="JPEG", quality=88, optimize=True)
    return base64.b64encode(prepared_path.read_bytes()).decode("ascii")


def _pdf_page_payloads(path: Path, tmp_dir: Path, remaining_slots: int) -> list[str]:
    output_prefix = tmp_dir / f"{path.stem}-page"
    subprocess.run(
        ["pdftoppm", "-png", "-r", "180", str(path), str(output_prefix)],
        check=True,
        capture_output=True,
        text=True,
    )
    payloads = []
    for page in sorted(tmp_dir.glob(f"{path.stem}-page-*.png"))[:remaining_slots]:
        payloads.append(_prepare_image_payload(page, tmp_dir))
    return payloads


def build_extraction_image_payloads(document: Document) -> list[str]:
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

    payloads = []
    with tempfile.TemporaryDirectory() as raw_tmp_dir:
        tmp_dir = Path(raw_tmp_dir)
        for document_file in sorted(files, key=lambda item: item.sort_order):
            if len(payloads) >= settings.extraction_max_images:
                break
            path = Path(document_file.storage_path)
            if not path.exists():
                raise FileNotFoundError(f"Document file not found: {path}")
            if document_file.mime_type == "application/pdf":
                payloads.extend(_pdf_page_payloads(path, tmp_dir, settings.extraction_max_images - len(payloads)))
            elif document_file.mime_type.startswith("image/"):
                payloads.append(_prepare_image_payload(path, tmp_dir))

    return payloads[: settings.extraction_max_images]


def parse_extraction_response(response_text: str) -> dict:
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    data = json.loads(cleaned.strip())
    missing = REQUIRED_KEYS - set(data)
    if missing:
        raise ValueError(f"Missing extraction keys: {', '.join(sorted(missing))}")
    return data


def build_structured_rag_text(document: Document, ocr_result: OcrResult, extraction: dict) -> str:
    merchant = extraction.get("merchant") or {}
    order = extraction.get("order") or {}
    payment = extraction.get("payment") or {}
    buyer = extraction.get("buyer") or {}
    registered_address = merchant.get("registered_address") or extraction.get("registered_office_address") or {}
    store_address = merchant.get("store_address") or extraction.get("business_premises_address") or extraction.get("place") or {}
    billing_address = buyer.get("billing_address") or extraction.get("billing_address") or {}
    delivery_address = buyer.get("delivery_address") or extraction.get("delivery_address") or {}
    total = payment.get("total") or extraction.get("total") or {}
    items = extraction.get("items") or []
    item_names = []
    for item in items[:12]:
        name = item.get("name") or item.get("raw")
        user_label = item.get("user_label")
        user_note = item.get("user_note")
        quantity = item.get("quantity")
        unit = item.get("unit")
        unit_price = item.get("unit_price")
        total_price = item.get("total_price")
        raw = item.get("raw")
        details = []
        if quantity is not None:
            details.append(f"mnozstvi: {quantity}{f' {unit}' if unit else ''}")
        if unit_price is not None:
            details.append(f"jednotkova cena: {unit_price}")
        if raw:
            details.append(f"raw: {raw}")
        if user_label:
            details.append(f"uzivatelsky nazev: {user_label}")
        if user_note:
            details.append(f"poznamka: {user_note}")
        if name and total_price:
            suffix = f"; {'; '.join(details)}" if details else ""
            item_names.append(f"{name} ({total_price}{suffix})")
        elif name:
            suffix = f" ({'; '.join(details)})" if details else ""
            item_names.append(f"{name}{suffix}")
        elif user_label:
            item_names.append(str(user_label))

    sections = [
        f"Popis: {extraction.get('summary')}" if extraction.get("summary") else "",
        f"Doklad: {extraction.get('document_type') or 'unknown'}",
        f"Soubor: {document.filename}",
        f"Datum vystaveni: {extraction.get('issue_date')}",
        f"Datum splatnosti: {extraction.get('due_date')}",
        f"Cislo faktury: {extraction.get('invoice_number')}",
        f"Dodaci list: {extraction.get('delivery_note_number')}",
        f"Cislo objednavky: {order.get('order_number') or extraction.get('order_number')}",
        f"Variabilni symbol: {payment.get('variable_symbol') or extraction.get('variable_symbol')}",
        f"Konstantni symbol: {payment.get('constant_symbol') or extraction.get('constant_symbol')}",
        f"Obchod: {merchant.get('name')}",
        f"ICO dodavatele: {merchant.get('ico')}",
        f"DIC dodavatele: {merchant.get('dic')}",
        f"Sidlo spolecnosti: {registered_address.get('raw')}",
        f"Provozovna: {store_address.get('raw')}",
        f"Odberatel: {buyer.get('name')}",
        f"Fakturacni adresa: {billing_address.get('raw')}",
        f"Dodaci adresa: {delivery_address.get('raw')}",
        f"Cena celkem: {total.get('raw') or total.get('amount')}",
        f"Zpusob uhrady: {payment.get('payment_method') or extraction.get('payment_method')}",
        f"Mena: {payment.get('currency') or extraction.get('currency')}",
    ]
    if item_names:
        sections.append(f"Polozky: {'; '.join(item_names)}")
    return "\n".join(line for line in sections if line and not line.endswith("None")).strip()


async def process_extraction_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    client: OllamaClient | None = None,
) -> ProcessingJob:
    result = await session.execute(
        select(ProcessingJob).where(ProcessingJob.id == job_id, ProcessingJob.kind == JobKind.extraction)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise ValueError("Extraction job not found")

    document_result = await session.execute(
        select(Document)
        .where(Document.id == job.document_id, Document.user_id == job.user_id)
        .options(selectinload(Document.files))
    )
    document = document_result.scalar_one_or_none()
    ocr_result = None
    if document is not None:
        ocr_query = await session.execute(
            select(OcrResult).where(OcrResult.document_id == document.id, OcrResult.user_id == document.user_id)
        )
        ocr_result = ocr_query.scalar_one_or_none()

    if document is None or ocr_result is None:
        job.status = JobStatus.failed
        job.error_message = "OCR result not found"
        await session.commit()
        return job

    job.status = JobStatus.running
    job.error_message = None
    await session.commit()

    settings_result = await session.execute(select(UserSettings).where(UserSettings.user_id == job.user_id))
    user_settings = settings_result.scalar_one_or_none()
    model = (
        user_settings.ocr_processing_model
        if user_settings and user_settings.ocr_processing_model
        else settings.extraction_model or settings.ollama_model
    )
    try:
        prompt = build_extraction_prompt(document, ocr_result)
        llm_client = client or OllamaClient(await get_role_server(session, "structuring"))
        image_payloads = []
        if settings.extraction_mode.strip().lower() == "vision_hybrid":
            image_payloads = build_extraction_image_payloads(document)

        if image_payloads:
            raw_response = await llm_client.extract_json_with_images(prompt, image_payloads, model=model)
            extraction_mode = "vision_hybrid"
        else:
            raw_response = await llm_client.extract_json(prompt, model=model)
            extraction_mode = "text_only"
        structured = parse_extraction_response(raw_response)
        extraction_result = await session.execute(
            select(DocumentExtraction).where(
                DocumentExtraction.document_id == document.id,
                DocumentExtraction.user_id == document.user_id,
            )
        )
        extraction = extraction_result.scalar_one_or_none()
        if extraction is None:
            extraction = DocumentExtraction(
                id=uuid.uuid4(),
                document_id=document.id,
                user_id=document.user_id,
                structured_json={},
                summary="",
                review_status="draft",
                model=model,
                raw_response="",
            )
            session.add(extraction)

        extraction.structured_json = structured
        extraction.summary = structured.get("summary") or ""
        extraction.review_status = "draft"
        extraction.model = model
        extraction.raw_response = raw_response
        ocr_result.rag_text = build_structured_rag_text(document, ocr_result, structured)
        rag_indexed = await index_document_rag_text(session, document, ocr_result.rag_text, structured)
        job.status = JobStatus.succeeded
        job.payload = {
            **(job.payload or {}),
            "extraction_id": str(extraction.id),
            "model": model,
            "extraction_mode": extraction_mode,
            "image_count": len(image_payloads),
            "rag_indexed": rag_indexed,
            "rag_embedding_model": settings.rag_embedding_model,
        }
    except Exception as exc:
        job.status = JobStatus.failed
        job.error_message = str(exc)

    await session.commit()
    await session.refresh(job)
    return job


async def process_next_extraction_job(session: AsyncSession, client: OllamaClient | None = None) -> ProcessingJob | None:
    result = await session.execute(
        select(ProcessingJob)
        .where(ProcessingJob.kind == JobKind.extraction, ProcessingJob.status == JobStatus.queued)
        .order_by(ProcessingJob.created_at)
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None
    return await process_extraction_job(session, job.id, client=client)
