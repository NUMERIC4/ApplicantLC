import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai_service import JobExtractionServiceError, ai_service
from backend.database import get_db
from backend.job_ingestion import JobIngestionError, fetch_job_page, normalize_source_url, prepare_pasted_source, source_hash
from backend.models import Company, Job, JobRequirement
from backend.schemas import JobConfirmRequest, JobConfirmResponse, JobDuplicateInfo, JobDuplicateResponse, JobIngestRequest, JobIngestResponse, JobManualVersionRequest, JobPasteTextRequest, JobUpdateCheckRequest

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])


def _error_response(error: JobIngestionError | JobExtractionServiceError) -> HTTPException:
    return HTTPException(status_code=error.status_code if isinstance(error, JobIngestionError) else 502, detail={"code": error.code, "message": error.message})


async def _latest_for_url(db: AsyncSession, normalized_url: str) -> Optional[Job]:
    result = await db.execute(select(Job).where(Job.normalized_source_url == normalized_url, Job.confirmation_status == "confirmed").order_by(Job.version_number.desc(), Job.confirmed_at.desc(), Job.id.desc()))
    return result.scalars().first()


async def _company(db: AsyncSession, job: Job) -> Company:
    return (await db.execute(select(Company).where(Company.id == job.company_id))).scalars().one()


async def _requirements(db: AsyncSession, job_id: int) -> list[JobRequirement]:
    return list((await db.execute(select(JobRequirement).where(JobRequirement.job_id == job_id))).scalars().all())


async def _ensure_latest(db: AsyncSession, job: Job) -> None:
    child = await db.execute(select(Job.id).where(Job.supersedes_job_id == job.id, Job.confirmation_status == "confirmed").limit(1))
    if child.scalar_one_or_none() is not None:
        raise HTTPException(409, detail={"code": "not_latest_version", "message": "Start edits from the latest confirmed Job version."})


async def _find_or_create_company(db: AsyncSession, name: str) -> Company:
    name = name.strip()
    company = (await db.execute(select(Company).where(func.lower(Company.name) == name.lower()))).scalars().first()
    if company is None:
        company = Company(name=name)
        db.add(company)
        await db.flush()
    return company


async def _persist(
    db: AsyncSession, payload: JobConfirmRequest | JobManualVersionRequest, *, version_source: str,
    previous: Optional[Job] = None, source_text: Optional[str] = None,
    normalized_url: Optional[str] = None, stored_hash: Optional[str] = None,
) -> tuple[Company, Job, list[JobRequirement]]:
    """Create one confirmed, immutable Job version and reviewed requirements."""
    company = await _find_or_create_company(db, payload.company_name)
    url = getattr(payload, "source_url", None) or (previous.source_url if previous else None)
    normalized_url = normalized_url if normalized_url is not None else (normalize_source_url(url) if url else (previous.normalized_source_url if previous else None))
    source_text = source_text if source_text is not None else (previous.raw_source_text if previous else None)
    now = datetime.utcnow()
    job = Job(
        company_id=company.id, title=payload.position_title.strip(), source_url=url.strip() if url else None,
        normalized_source_url=normalized_url,
        source_hash=stored_hash or (source_hash(source_text) if source_text else (previous.source_hash if previous else None)),
        description=payload.job_description, location=payload.location, source_platform=payload.source_platform,
        raw_source_text=source_text, structured_extraction=json.dumps(payload.model_dump(mode="json"), ensure_ascii=False),
        confirmation_status="confirmed", version_number=previous.version_number + 1 if previous else 1,
        supersedes_job_id=previous.id if previous else None, version_source=version_source,
        confirmed_at=now, last_edited_at=now if version_source == "manual_correction" else None,
    )
    db.add(job)
    await db.flush()
    requirements: list[JobRequirement] = []
    seen: set[str] = set()
    for importance, items in (("required", payload.required_qualifications), ("preferred", payload.preferred_qualifications)):
        for item in items:
            requirement = " ".join(item.text.split())
            if not requirement or requirement.casefold() in seen:
                continue
            seen.add(requirement.casefold())
            record = JobRequirement(job_id=job.id, requirement=requirement, category=item.category, importance=importance, source_text=item.source_evidence)
            db.add(record)
            requirements.append(record)
    await db.commit()
    await db.refresh(company)
    await db.refresh(job)
    for record in requirements:
        await db.refresh(record)
    return company, job, requirements


@router.post("/ingest", response_model=None)
async def ingest_job_url(payload: JobIngestRequest, db: AsyncSession = Depends(get_db)):
    """Duplicate lookup precedes any fetch or NVIDIA extraction."""
    try:
        normalized_url = normalize_source_url(payload.url)
    except JobIngestionError as error:
        raise _error_response(error) from None
    existing = await _latest_for_url(db, normalized_url)
    if existing:
        company = await _company(db, existing)
        return JobDuplicateResponse(normalized_source_url=normalized_url, latest_job=JobDuplicateInfo(id=existing.id, company_name=company.name, title=existing.title, version_number=existing.version_number, confirmed_at=existing.confirmed_at, source_url=existing.source_url, version_source=existing.version_source))
    try:
        page = await fetch_job_page(payload.url)
        extraction = await ai_service.extract_job_structured(source_url=page.source_url, source_text=page.source_text, source_platform=page.source_platform)
    except (JobIngestionError, JobExtractionServiceError) as error:
        raise _error_response(error) from None
    return JobIngestResponse(preview=extraction.preview, source_text=page.source_text, source_text_truncated=page.source_text_truncated, page_title=page.page_title, canonical_url=page.canonical_url, latency_ms=extraction.latency_ms, usage=extraction.usage, response_format_json=extraction.response_format_json, thinking_disabled=extraction.thinking_disabled)


@router.post("/check-update", response_model=None)
async def check_job_update(payload: JobUpdateCheckRequest, db: AsyncSession = Depends(get_db)):
    try:
        normalized_url = normalize_source_url(payload.url)
    except JobIngestionError as error:
        raise _error_response(error) from None
    existing = await _latest_for_url(db, normalized_url)
    if existing is None:
        raise HTTPException(404, detail={"code": "job_not_found", "message": "No confirmed Job exists for this URL."})
    try:
        page = await fetch_job_page(payload.url)
    except JobIngestionError as error:
        raise _error_response(error) from None
    new_hash = source_hash(page.source_text)
    if existing.source_hash and existing.source_hash == new_hash:
        return {"state": "unchanged", "message": "No source changes were detected.", "existing_job_id": existing.id}
    try:
        extraction = await ai_service.extract_job_structured(source_url=page.source_url, source_text=page.source_text, source_platform=page.source_platform)
    except JobExtractionServiceError as error:
        raise _error_response(error) from None
    result = JobIngestResponse(preview=extraction.preview, source_text=page.source_text, source_text_truncated=page.source_text_truncated, page_title=page.page_title, canonical_url=page.canonical_url, latency_ms=extraction.latency_ms, usage=extraction.usage, response_format_json=extraction.response_format_json, thinking_disabled=extraction.thinking_disabled).model_dump(mode="json")
    result.update({"message": "Updated source detected — Review Required", "existing_job_id": existing.id, "source_hash": new_hash})
    return result


@router.post("/extract-text", response_model=JobIngestResponse)
async def extract_job_text(payload: JobPasteTextRequest):
    try:
        cleaned, truncated = prepare_pasted_source(payload.text)
        extraction = await ai_service.extract_job_structured(source_url="", source_text=cleaned, source_platform="manual")
    except (JobIngestionError, JobExtractionServiceError) as error:
        raise _error_response(error) from None
    preview = extraction.preview.model_copy(update={"source_url": None, "source_platform": "manual"})
    return JobIngestResponse(preview=preview, source_text=cleaned, source_text_truncated=truncated, page_title=None, canonical_url=None, latency_ms=extraction.latency_ms, usage=extraction.usage, response_format_json=extraction.response_format_json, thinking_disabled=extraction.thinking_disabled)


@router.post("/confirm", response_model=JobConfirmResponse)
async def confirm_job(payload: JobConfirmRequest, db: AsyncSession = Depends(get_db)):
    previous = None
    if payload.supersedes_job_id is not None:
        previous = (await db.execute(select(Job).where(Job.id == payload.supersedes_job_id))).scalars().first()
        if previous is None or previous.confirmation_status != "confirmed":
            raise HTTPException(404, detail={"code": "job_not_found", "message": "The prior confirmed Job was not found."})
        await _ensure_latest(db, previous)
    if payload.version_source == "source_update" and previous is None:
        raise HTTPException(422, detail={"code": "missing_previous_version", "message": "A source update must identify its prior Job version."})
    if payload.version_source == "pasted_text" and payload.source_url:
        raise HTTPException(422, detail={"code": "invalid_pasted_source", "message": "Pasted job text must not invent a source URL."})
    normalized = normalize_source_url(payload.source_url) if payload.source_url else None
    company, job, requirements = await _persist(db, payload, version_source=payload.version_source, previous=previous, source_text=payload.source_text, normalized_url=normalized, stored_hash=payload.source_hash)
    return JobConfirmResponse(company=company, job=job, requirements=requirements)


@router.get("/{job_id}", response_model=JobConfirmResponse)
async def open_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalars().first()
    if job is None:
        raise HTTPException(404, detail={"code": "job_not_found", "message": "The Job was not found."})
    return JobConfirmResponse(company=await _company(db, job), job=job, requirements=await _requirements(db, job.id))


@router.post("/{job_id}/manual-version", response_model=JobConfirmResponse)
async def create_manual_job_version(job_id: int, payload: JobManualVersionRequest, db: AsyncSession = Depends(get_db)):
    previous = (await db.execute(select(Job).where(Job.id == job_id))).scalars().first()
    if previous is None or previous.confirmation_status != "confirmed":
        raise HTTPException(404, detail={"code": "job_not_found", "message": "The confirmed Job was not found."})
    await _ensure_latest(db, previous)
    company, job, requirements = await _persist(db, payload, version_source="manual_correction", previous=previous, source_text=previous.raw_source_text, normalized_url=previous.normalized_source_url, stored_hash=previous.source_hash)
    return JobConfirmResponse(company=company, job=job, requirements=requirements)
