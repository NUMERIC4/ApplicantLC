"""Local-only PDF validation, text extraction, hashing, and safe file storage."""

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from backend.config import settings
from backend.cv_layout import LayoutExtractionError, reconstruct_pdf


class CVIngestionError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code, self.message, self.status_code = code, message, status_code
        super().__init__(message)


@dataclass(frozen=True)
class ExtractedCVText:
    text: str
    text_hash: str
    parser_version: str = "linear_v1"
    layout_metadata: dict = field(default_factory=dict)
    layout_confidence: str = "low"
    warnings: list[str] = field(default_factory=list)
    timing_ms: dict[str, int] = field(default_factory=dict)


def normalize_cv_text(value: str) -> str:
    return " ".join(value.replace("\r\n", "\n").replace("\r", "\n").split())


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_original_filename(value: str | None) -> str:
    name = Path(value or "cv.pdf").name.replace("\x00", "").strip()
    return name[:255] or "cv.pdf"


def validate_pdf_upload(data: bytes, filename: str | None) -> str:
    if not data:
        raise CVIngestionError("empty_file", "The uploaded CV file is empty.")
    if len(data) > settings.CV_MAX_FILE_MB * 1024 * 1024:
        raise CVIngestionError("file_too_large", f"PDF uploads are limited to {settings.CV_MAX_FILE_MB} MB.")
    safe_name = safe_original_filename(filename)
    if not safe_name.lower().endswith(".pdf") or not data.startswith(b"%PDF-"):
        raise CVIngestionError("invalid_pdf", "Only valid PDF CV uploads are supported.")
    return safe_name


def extract_pdf_text(data: bytes) -> ExtractedCVText:
    """Prefer layout_v2 reconstruction; keep pypdf as clearly-marked fallback."""
    started = time.perf_counter()
    try:
        reconstruction_started = time.perf_counter()
        layout = reconstruct_pdf(data)
        reconstruction_ms = round((time.perf_counter() - reconstruction_started) * 1000)
        model_text = layout.model_text
        quality_text = layout.plain_text
        parser_version = layout.parser_version
        metadata = layout.metadata
        confidence = layout.layout_confidence
        warnings = layout.warnings
    except LayoutExtractionError:
        reconstruction_ms = round((time.perf_counter() - started) * 1000)
        try:
            reader = PdfReader(BytesIO(data))
            quality_text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            raise CVIngestionError("invalid_pdf", "The uploaded file could not be read as a PDF.") from None
        model_text = quality_text
        parser_version = "linear_v1"
        metadata = {"pages": len(reader.pages), "blocks": 0, "layout_regions": 0, "fallback_used": True}
        confidence = "low"
        warnings = ["Positioned layout reconstruction was unavailable; legacy linear text extraction was used."]
    normalized = normalize_cv_text(model_text)
    normalized_quality = normalize_cv_text(quality_text)
    broken_ratio = quality_text.count("\ufffd") / max(len(quality_text), 1)
    if len(normalized_quality) < 80 or broken_ratio > 0.1:
        raise CVIngestionError("unusable_pdf_text", "This PDF does not contain enough extractable text. Scanned CV OCR is not supported yet.")
    if len(normalized) > settings.CV_SOURCE_MAX_CHARS:
        raise CVIngestionError("source_text_too_large", "This CV contains more extractable text than the configured processing limit. Reduce the document before upload.")
    return ExtractedCVText(text=normalized, text_hash=sha256_bytes(normalized.encode("utf-8")), parser_version=parser_version, layout_metadata=metadata, layout_confidence=confidence, warnings=warnings, timing_ms={"pdf_extraction": round((time.perf_counter() - started) * 1000), "layout_reconstruction": reconstruction_ms})


def store_pdf(candidate_id: int, data: bytes) -> str:
    """Store under a generated name and return only an application-relative path."""
    root = Path(settings.APPLICANT_FILES_DIR).resolve()
    candidate_dir = (root / f"candidate_{candidate_id}").resolve()
    if root not in candidate_dir.parents:
        raise CVIngestionError("storage_error", "CV storage path could not be prepared.", 500)
    candidate_dir.mkdir(parents=True, exist_ok=True)
    target = candidate_dir / f"{uuid.uuid4().hex}.pdf"
    target.write_bytes(data)
    return target.relative_to(Path.cwd().resolve()).as_posix()
