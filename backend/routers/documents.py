import json
import time
from asyncio import Lock
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai_service import CVExtractionServiceError, ai_service
from backend.config import settings
from backend.cv_ingestion import CVIngestionError, extract_pdf_text, sha256_bytes, store_pdf, validate_pdf_upload
from backend.cv_layout import CURRENT_CV_PARSER_VERSION
from backend.database import get_db
from backend.models import Candidate, Document
from backend.resume_parser import ResumeParserProviderError, affinda_resume_parser
from backend.schemas import CVConfirmRequest, CVProfile, CVProviderPreviewRequest, CVReprocessRequest, DocumentCreate, DocumentRead

router = APIRouter(prefix="/api/documents", tags=["Documents"])
_reprocess_lock = Lock()
_reprocessing_document_ids: set[int] = set()
_provider_preview_lock = Lock()
_provider_preview_document_ids: set[int] = set()


def _error(error: CVIngestionError | CVExtractionServiceError) -> HTTPException:
    return HTTPException(error.status_code if isinstance(error, CVIngestionError) else 502, detail={"code": error.code, "message": error.message})


def _provider_error(error: ResumeParserProviderError) -> JSONResponse:
    """Stable, sanitized comparison failure; never proxy raw provider data."""
    return JSONResponse(status_code=error.status_code, content={
        "success": False, "provider": "affinda", "upstream_status": error.upstream_status,
        "code": error.provider_code, "provider_code": error.provider_code,
        "message": error.provider_message, "provider_message": error.provider_message,
        "retryable": error.retryable, "retry_after_seconds": error.retry_after_seconds,
    })


async def _candidate(db: AsyncSession, candidate_id: int) -> Candidate:
    candidate = (await db.execute(select(Candidate).where(Candidate.id == candidate_id))).scalars().first()
    if candidate is None:
        raise HTTPException(404, detail={"code": "candidate_not_found", "message": "The selected candidate was not found."})
    return candidate


def _safe_external_url(value: Optional[str]) -> bool:
    from urllib.parse import urlsplit
    parsed = urlsplit(value or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _local_path(document: Document) -> Optional[Path]:
    """Resolve only a candidate-owned file beneath the configured storage root."""
    if not document.stored_path or not document.candidate_id:
        return None
    root = Path(settings.APPLICANT_FILES_DIR).resolve()
    candidate_root = (root / f"candidate_{document.candidate_id}").resolve()
    target = Path(document.stored_path).resolve()
    if root not in target.parents or candidate_root not in target.parents or not target.is_file():
        return None
    return target


def _document_data(document: Document) -> dict:
    has_local = _local_path(document) is not None
    is_cv = document.doc_type == "CV"
    external = _safe_external_url(document.file_link)
    data = DocumentRead.model_validate(document).model_dump(mode="json")
    data.update({
        "has_local_file": has_local,
        "can_open_file": has_local or external,
        "can_reprocess": is_cv and document.confirmation_status == "unconfirmed" and has_local and document.parser_version != CURRENT_CV_PARSER_VERSION,
        "can_compare_affinda": is_cv and has_local and affinda_resume_parser.configuration_status()["configured"],
        "is_confirmed": document.confirmation_status == "confirmed",
        "file_open_mode": "local" if has_local else "external" if external else None,
    })
    return data


def _profile(document: Document) -> Optional[CVProfile]:
    if not document.structured_extraction:
        return None
    try:
        return CVProfile.model_validate(json.loads(document.structured_extraction))
    except Exception:
        return None


async def _new_document(db: AsyncSession, *, candidate_id: int, name: str, stored_path: str, file_hash: str, raw_text: Optional[str] = None, text_hash: Optional[str] = None, parser_version: Optional[str] = None, layout_metadata: Optional[dict] = None, layout_confidence: Optional[str] = None, extraction_error: Optional[str] = None) -> Document:
    document = Document(candidate_id=candidate_id, name=name, doc_type="CV", stored_path=stored_path, file_hash=file_hash, raw_text=raw_text, text_hash=text_hash, parser_version=parser_version, layout_metadata=json.dumps(layout_metadata, ensure_ascii=False) if layout_metadata else None, layout_confidence=layout_confidence, confirmation_status="unconfirmed", extraction_error=extraction_error, extracted_at=datetime.utcnow() if raw_text else None)
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


@router.post("/cv/upload", response_model=None)
async def upload_cv(candidate_id: int = Form(...), file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Upload one PDF into candidate-private storage and create only an unconfirmed profile."""
    await _candidate(db, candidate_id)
    started = time.perf_counter()
    data = await file.read(settings.CV_MAX_FILE_MB * 1024 * 1024 + 1)
    try:
        original_name = validate_pdf_upload(data, file.filename)
    except CVIngestionError as error:
        raise _error(error) from None
    file_hash = sha256_bytes(data)
    existing = (await db.execute(select(Document).where(Document.candidate_id == candidate_id, Document.file_hash == file_hash))).scalars().first()
    if existing:
        capabilities = _document_data(existing)
        return {"state": "duplicate", "message": "This exact CV file already exists.", "document": capabilities, "profile": _profile(existing).model_dump(mode="json") if _profile(existing) else None, "reprocess_available": capabilities["can_reprocess"], "timing_ms": {"total": round((time.perf_counter() - started) * 1000)}}

    stored_path = store_pdf(candidate_id, data)
    try:
        extraction_started = time.perf_counter()
        extracted = extract_pdf_text(data)
        extraction_ms = round((time.perf_counter() - extraction_started) * 1000)
    except CVIngestionError as error:
        document = await _new_document(db, candidate_id=candidate_id, name=original_name, stored_path=stored_path, file_hash=file_hash, extraction_error=error.message)
        raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message, "document_id": document.id}) from None

    matching = (await db.execute(select(Document).where(Document.candidate_id == candidate_id, Document.text_hash == extracted.text_hash, Document.parser_version == extracted.parser_version).order_by(Document.confirmed_at.desc(), Document.id.desc()))).scalars().first()
    if matching and matching.structured_extraction:
        document = await _new_document(db, candidate_id=candidate_id, name=original_name, stored_path=stored_path, file_hash=file_hash, raw_text=extracted.text, text_hash=extracted.text_hash, parser_version=extracted.parser_version, layout_metadata={**extracted.layout_metadata, "warnings": extracted.warnings}, layout_confidence=extracted.layout_confidence)
        document.structured_extraction = matching.structured_extraction
        document.extraction_confidence = matching.extraction_confidence
        if matching.confirmation_status == "confirmed":
            document.confirmation_status = "confirmed"
            document.confirmed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(document)
        return {"state": "reused", "message": "This PDF has the same extracted content as an existing CV; its structured profile was reused without AI analysis.", "document": _document_data(document), "profile": _profile(document).model_dump(mode="json") if _profile(document) else None, "reused_from_document_id": matching.id, "timing_ms": {**extracted.timing_ms, "total": round((time.perf_counter() - started) * 1000)}}

    document = await _new_document(db, candidate_id=candidate_id, name=original_name, stored_path=stored_path, file_hash=file_hash, raw_text=extracted.text, text_hash=extracted.text_hash, parser_version=extracted.parser_version, layout_metadata={**extracted.layout_metadata, "warnings": extracted.warnings}, layout_confidence=extracted.layout_confidence)
    try:
        result = await ai_service.extract_cv_profile(extracted.text)
    except CVExtractionServiceError as error:
        document.extraction_error = error.message
        await db.commit()
        raise _error(error) from None
    profile = result.profile.model_copy(update={"extraction_warnings": [*extracted.warnings, *result.profile.extraction_warnings]})
    document.structured_extraction = json.dumps(profile.model_dump(mode="json"), ensure_ascii=False)
    document.extraction_confidence = result.profile.extraction_confidence
    document.extraction_error = None
    await db.commit()
    await db.refresh(document)
    return {"state": "preview", "document": _document_data(document), "profile": profile.model_dump(mode="json"), "latency_ms": result.latency_ms, "usage": result.usage, "response_format_json": result.response_format_json, "thinking_disabled": result.thinking_disabled, "timing_ms": {**extracted.timing_ms, "ai_inference": result.latency_ms, "total": round((time.perf_counter() - started) * 1000)}}


@router.get("/cv/{document_id}", response_model=None)
async def open_cv(document_id: int, candidate_id: int, db: AsyncSession = Depends(get_db)):
    document = (await db.execute(select(Document).where(Document.id == document_id, Document.candidate_id == candidate_id, Document.doc_type == "CV"))).scalars().first()
    if document is None:
        raise HTTPException(404, detail={"code": "document_not_found", "message": "The candidate CV was not found."})
    return {"document": _document_data(document), "profile": _profile(document).model_dump(mode="json") if _profile(document) else None}


@router.get("/providers/affinda/status")
async def affinda_status():
    """Safe, read-only configuration status; never contains the API key."""
    return affinda_resume_parser.configuration_status()


@router.post("/cv/{document_id}/provider-preview", response_model=None)
async def preview_cv_provider(document_id: int, payload: CVProviderPreviewRequest, db: AsyncSession = Depends(get_db)):
    """Explicit one-shot cloud comparison. It never writes to the Document."""
    document = (await db.execute(select(Document).where(
        Document.id == document_id, Document.candidate_id == payload.candidate_id, Document.doc_type == "CV"
    ))).scalars().first()
    if document is None:
        raise HTTPException(404, detail={"code": "document_not_found", "message": "The candidate CV was not found."})
    source = _local_path(document)
    if source is None:
        raise HTTPException(409, detail={"code": "stored_file_missing", "message": "The locally stored PDF is unavailable for comparison."})
    if not affinda_resume_parser.configuration_status()["configured"]:
        return _provider_error(ResumeParserProviderError("provider_not_configured", "Affinda is not configured on this server.", 503, provider_code="provider_not_configured", provider_message="Affinda is not configured on this server."))
    async with _provider_preview_lock:
        if document_id in _provider_preview_document_ids:
            raise HTTPException(409, detail={"code": "already_processing", "message": "This CV already has an Affinda comparison in progress."})
        _provider_preview_document_ids.add(document_id)
    try:
        try:
            preview = await affinda_resume_parser.parse_pdf(source.read_bytes(), document.name)
        except ResumeParserProviderError as error:
            return _provider_error(error)
        return {
            "success": True, "provider": preview.provider,
            "current_profile": _profile(document).model_dump(mode="json") if _profile(document) else None,
            "profile": preview.profile.model_dump(mode="json"), "coverage": preview.coverage,
            "coverage_gaps": preview.coverage_gaps, "latency_ms": preview.latency_ms,
            "http_status": preview.http_status, "credits_remaining": preview.credits_remaining,
            "schema_version": preview.schema_version, "classification": preview.classification,
            "extraction_quality": preview.extraction_quality,
        }
    finally:
        async with _provider_preview_lock:
            _provider_preview_document_ids.discard(document_id)


@router.get("/{document_id}/file")
async def open_document_file(document_id: int, candidate_id: int, db: AsyncSession = Depends(get_db)):
    """Serve a candidate-owned local PDF, or safely redirect a legacy external link."""
    document = (await db.execute(select(Document).where(Document.id == document_id, Document.candidate_id == candidate_id))).scalars().first()
    if document is None:
        raise HTTPException(404, detail={"code": "document_not_found", "message": "The candidate document was not found."})
    local_file = _local_path(document)
    if local_file:
        safe_name = Path(document.name or "document.pdf").name
        return FileResponse(local_file, media_type="application/pdf", filename=safe_name, content_disposition_type="inline")
    if _safe_external_url(document.file_link):
        return RedirectResponse(document.file_link, status_code=307)
    raise HTTPException(404, detail={"code": "local_file_unavailable", "message": "No local file is available for this legacy document."})


@router.post("/cv/{document_id}/confirm", response_model=None)
async def confirm_cv(document_id: int, payload: CVConfirmRequest, db: AsyncSession = Depends(get_db)):
    document = (await db.execute(select(Document).where(Document.id == document_id, Document.candidate_id == payload.candidate_id, Document.doc_type == "CV"))).scalars().first()
    if document is None:
        raise HTTPException(404, detail={"code": "document_not_found", "message": "The candidate CV was not found."})
    document.structured_extraction = json.dumps(payload.profile.model_dump(mode="json"), ensure_ascii=False)
    document.extraction_confidence = payload.profile.extraction_confidence
    document.confirmation_status = "confirmed"
    document.confirmed_at = datetime.utcnow()
    document.extraction_error = None
    await db.commit()
    await db.refresh(document)
    return {"document": _document_data(document), "profile": payload.profile.model_dump(mode="json")}


@router.post("/cv/{document_id}/reprocess", response_model=None)
async def reprocess_cv(document_id: int, payload: CVReprocessRequest, db: AsyncSession = Depends(get_db)):
    """Explicitly replace only an unconfirmed review using the stored original PDF."""
    document = (await db.execute(select(Document).where(Document.id == document_id, Document.candidate_id == payload.candidate_id, Document.doc_type == "CV"))).scalars().first()
    if document is None:
        raise HTTPException(404, detail={"code": "document_not_found", "message": "The candidate CV was not found."})
    if document.confirmation_status == "confirmed":
        raise HTTPException(409, detail={"code": "confirmed_cv_immutable", "message": "Confirmed CV profiles are not reprocessed without versioning design."})
    source = _local_path(document)
    if source is None:
        raise HTTPException(409, detail={"code": "stored_file_missing", "message": "The locally stored PDF is unavailable for reprocessing."})
    async with _reprocess_lock:
        if document_id in _reprocessing_document_ids:
            raise HTTPException(409, detail={"code": "already_processing", "message": "This CV is already being reprocessed."})
        _reprocessing_document_ids.add(document_id)
    started = time.perf_counter()
    try:
        try:
            extraction_started = time.perf_counter()
            extracted = extract_pdf_text(source.read_bytes())
            extraction_ms = round((time.perf_counter() - extraction_started) * 1000)
            result = await ai_service.extract_cv_profile(extracted.text)
        except CVIngestionError as error:
            document.extraction_error = error.message
            await db.commit()
            raise _error(error) from None
        except CVExtractionServiceError as error:
            document.extraction_error = error.message
            await db.commit()
            raise _error(error) from None
        profile = result.profile.model_copy(update={"extraction_warnings": [*extracted.warnings, *result.profile.extraction_warnings]})
        document.raw_text = extracted.text
        document.text_hash = extracted.text_hash
        document.parser_version = extracted.parser_version
        document.layout_metadata = json.dumps({**extracted.layout_metadata, "warnings": extracted.warnings}, ensure_ascii=False)
        document.layout_confidence = extracted.layout_confidence
        document.structured_extraction = json.dumps(profile.model_dump(mode="json"), ensure_ascii=False)
        document.extraction_confidence = profile.extraction_confidence
        document.extracted_at = datetime.utcnow()
        document.extraction_error = None
        document.confirmation_status = "unconfirmed"
        await db.commit()
        await db.refresh(document)
        return {"state": "preview", "message": "CV reprocessed with the current parser. Review is still required.", "document": _document_data(document), "profile": profile.model_dump(mode="json"), "latency_ms": result.latency_ms, "usage": result.usage, "response_format_json": result.response_format_json, "thinking_disabled": result.thinking_disabled, "timing_ms": {**extracted.timing_ms, "ai_inference": result.latency_ms, "total": round((time.perf_counter() - started) * 1000)}}
    finally:
        async with _reprocess_lock:
            _reprocessing_document_ids.discard(document_id)


@router.get("", response_model=List[DocumentRead])
async def list_documents(doc_type: Optional[str] = None, candidate_id: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    query = select(Document)
    if doc_type:
        query = query.where(Document.doc_type == doc_type)
    if candidate_id is not None:
        query = query.where(Document.candidate_id == candidate_id)
    result = await db.execute(query.order_by(Document.version_date.desc(), Document.name.asc()))
    return [_document_data(document) for document in result.scalars().all()]


@router.post("", response_model=DocumentRead)
async def create_document(payload: DocumentCreate, db: AsyncSession = Depends(get_db)):
    doc = Document(**payload.model_dump())
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return _document_data(doc)


@router.put("/{document_id}", response_model=DocumentRead)
async def update_document(document_id: int, payload: dict, db: AsyncSession = Depends(get_db)):
    doc = (await db.execute(select(Document).where(Document.id == document_id))).scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    for key, value in payload.items():
        if hasattr(doc, key) and key not in {"stored_path", "file_hash", "text_hash", "raw_text", "structured_extraction"}:
            setattr(doc, key, value)
    await db.commit()
    await db.refresh(doc)
    return _document_data(doc)


@router.delete("/{document_id}")
async def delete_document(document_id: int, db: AsyncSession = Depends(get_db)):
    doc = (await db.execute(select(Document).where(Document.id == document_id))).scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    # Only remove a generated, application-controlled path; never use client input.
    if doc.stored_path:
        root = Path(settings.APPLICANT_FILES_DIR).resolve()
        target = _local_path(doc)
        if target:
            target.unlink()
    await db.delete(doc)
    await db.commit()
    return {"message": "Document deleted"}
