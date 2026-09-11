import json
from dataclasses import replace

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.config import settings
from backend.cv_ingestion import store_pdf
from backend.database import AsyncSessionLocal, init_db
from backend.models import Candidate, Document
from backend.resume_parser import AffindaResumeParserProvider, ResumeParserProviderError, normalize_affinda_response
from backend.routers import documents as documents_router
from backend.schemas import CVProfile


AFFINDA_SAMPLE = {
    "schemaVersion": "2026-01",
    "data": {
        "summary": "Source-provided summary",
        "isResumeProbability": 92,
        "education": [{"organization": "Example University", "accreditation": {"education": "B.Sc."}, "major": "Computer Science", "dates": {"startDate": "2022-10-01", "completionDate": "2025-09-01"}}],
        "workExperience": [{"organization": "Example Labs", "jobTitle": "Intern", "type": "volunteer", "jobDescription": "Supported testing.", "dates": {"startDate": "2024-01-01", "endDate": "2024-06-01"}}],
        "skills": [{"name": "Python", "type": "hard_skill"}, {"name": "python", "type": "hard_skill"}, {"name": "SQL"}],
        "languages": [{"name": "English", "proficiency": "C1"}, "German"],
        "certifications": ["Cloud Certificate"],
        "projects": [{"title": "Project One", "description": "Source project", "skills": ["Python"]}],
        "courses": [{"name": "Continuing course"}],
        "extractionQuality": {"band": "high", "score": 0.91},
        "unknownCategory": [{"name": "Never fabricate this"}],
    },
}


def configured(monkeypatch, key="test-affinda-secret"):
    monkeypatch.setattr(settings, "AFFINDA_API_KEY", key)
    monkeypatch.setattr(settings, "AFFINDA_BASE_URL", "https://resume-parser.eu1.affinda.com")
    monkeypatch.setattr(settings, "AFFINDA_REQUEST_TIMEOUT_SECONDS", 33.0)
    monkeypatch.setattr(settings, "RESUME_PARSER_PROVIDER", "local")


def provider_with(handler, captured=None):
    transport = httpx.MockTransport(handler)
    def factory(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return httpx.AsyncClient(transport=transport, **kwargs)
    return AffindaResumeParserProvider(client_factory=factory)


@pytest.mark.asyncio
async def test_affinda_uses_regional_url_bearer_and_one_multipart_pdf_request(monkeypatch):
    configured(monkeypatch)
    requests = []
    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json=AFFINDA_SAMPLE, headers={"x-credits-remaining": "17"})
    captured = {}
    preview = await provider_with(handler, captured).parse_pdf(b"%PDF-synthetic", "private-name.pdf")
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://resume-parser.eu1.affinda.com/v1/resumes/parse"
    assert request.headers["authorization"] == "Bearer test-affinda-secret"
    assert request.headers["content-type"].startswith("multipart/form-data;")
    assert b'name="file"' in request.content and b'filename="resume.pdf"' in request.content and b"Content-Type: application/pdf" in request.content
    assert captured["timeout"] == 33.0 and preview.credits_remaining == 17


@pytest.mark.asyncio
async def test_affinda_normalizes_supported_fields_and_reports_coverage_gaps(monkeypatch):
    configured(monkeypatch)
    async def handler(_request):
        return httpx.Response(200, json=AFFINDA_SAMPLE, headers={"x-credits-remaining": "not-a-number"})
    preview = await provider_with(handler).parse_pdf(b"%PDF", "resume.pdf")
    profile = preview.profile
    assert profile.education[0].institution == "Example University"
    assert profile.work_experience[0].position == "Intern"
    assert [item.name for item in profile.skills] == ["Python", "SQL"]
    assert profile.languages[0].level == "C1" and profile.languages[1].language == "German"
    assert profile.certifications[0].name == "Cloud Certificate"
    assert profile.projects[0].name == "Project One"
    assert profile.other_qualifications == []
    assert preview.coverage == {"skills": 2, "work_experience": 1, "education": 1, "languages": 2, "certifications": 1, "projects": 1, "continuing_education": 1, "volunteer_experience": 1}
    assert preview.classification == {"label": "resume", "confidence": 0.92}
    assert preview.extraction_quality == {"band": "high", "score": 0.91}
    assert len(preview.coverage_gaps) == 2 and preview.credits_remaining is None


@pytest.mark.asyncio
async def test_affinda_configuration_and_failures_are_sanitized_and_never_retried(monkeypatch):
    monkeypatch.setattr(settings, "AFFINDA_API_KEY", "")
    provider = AffindaResumeParserProvider()
    with pytest.raises(ResumeParserProviderError, match="not configured") as missing:
        await provider.parse_pdf(b"%PDF", "resume.pdf")
    assert missing.value.code == "provider_not_configured"

    configured(monkeypatch)
    calls = 0
    async def rate_handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(429, text="provider details must not escape")
    with pytest.raises(ResumeParserProviderError) as limited:
        await provider_with(rate_handler).parse_pdf(b"%PDF", "resume.pdf")
    assert limited.value.code == "rate_limited" and "details" not in limited.value.message and calls == 1

    async def auth_handler(_request): return httpx.Response(401)
    with pytest.raises(ResumeParserProviderError) as auth:
        await provider_with(auth_handler).parse_pdf(b"%PDF", "resume.pdf")
    assert auth.value.code == "unauthorized"

    async def malformed_handler(_request): return httpx.Response(200, content=b"not-json")
    with pytest.raises(ResumeParserProviderError) as malformed:
        await provider_with(malformed_handler).parse_pdf(b"%PDF", "resume.pdf")
    assert malformed.value.code == "invalid_provider_response"

    async def malformed_shape_handler(_request): return httpx.Response(200, json={"data": "not-an-object"})
    with pytest.raises(ResumeParserProviderError) as malformed_shape:
        await provider_with(malformed_shape_handler).parse_pdf(b"%PDF", "resume.pdf")
    assert malformed_shape.value.code == "invalid_provider_response"

    async def timeout_handler(_request): raise httpx.ReadTimeout("network detail")
    with pytest.raises(ResumeParserProviderError) as timeout:
        await provider_with(timeout_handler).parse_pdf(b"%PDF", "resume.pdf")
    assert timeout.value.code == "parser_timeout" and "network" not in timeout.value.message


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "provider_code", "retryable"), [
    (400, "missing_file", False), (401, "unauthorized", False), (402, "no_credits", False),
    (403, "unauthorized", False), (413, "document_too_large", False), (415, "unsupported_document", False),
    (422, "unsupported_document", False), (429, "rate_limited", True), (502, "parser_unavailable", True),
    (503, "parser_unavailable", True), (504, "deadline", True),
])
async def test_affinda_error_envelopes_keep_safe_code_status_and_retry_policy(monkeypatch, status, provider_code, retryable):
    configured(monkeypatch)
    async def handler(_request):
        return httpx.Response(status, json={"error": "raw upstream diagnostic must not be returned", "code": provider_code}, headers={"retry-after": "25"})
    with pytest.raises(ResumeParserProviderError) as failed:
        await provider_with(handler).parse_pdf(b"%PDF", "resume.pdf")
    error = failed.value
    assert error.upstream_status == status and error.provider_code == provider_code and error.retryable is retryable
    assert error.retry_after_seconds == 25 and "raw upstream" not in error.provider_message


async def candidate(name):
    await init_db()
    async with AsyncSessionLocal() as session:
        record = Candidate(profile_name=name)
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record


async def stored_cv(candidate_id, *, local=True):
    async with AsyncSessionLocal() as session:
        path = str(store_pdf(candidate_id, b"%PDF-synthetic")) if local else None
        profile = CVProfile(professional_summary="Saved profile", skills=[], work_experience=[], education=[], languages=[], certifications=[], projects=[], other_qualifications=[], extraction_confidence="medium", extraction_warnings=[])
        document = Document(candidate_id=candidate_id, name="private-cv.pdf", doc_type="CV", stored_path=path, structured_extraction=json.dumps(profile.model_dump()), confirmation_status="confirmed", parser_version="layout_v3", text_hash="unchanged")
        session.add(document)
        await session.commit()
        await session.refresh(document)
        return document


@pytest.mark.asyncio
async def test_safe_affinda_status_and_preview_are_candidate_scoped_and_non_destructive(monkeypatch):
    configured(monkeypatch)
    owner, other = await candidate("Affinda owner"), await candidate("Affinda other")
    document = await stored_cv(owner.id)
    calls = 0
    async def fake_parse(_pdf, _filename):
        nonlocal calls
        calls += 1
        return replace(normalize_affinda_response(AFFINDA_SAMPLE), latency_ms=12, http_status=200, credits_remaining=8)
    async def never_nvidia(_text):
        raise AssertionError("Affinda preview must never invoke NVIDIA")
    monkeypatch.setattr(documents_router.affinda_resume_parser, "parse_pdf", fake_parse)
    monkeypatch.setattr(documents_router.ai_service, "extract_cv_profile", never_nvidia)
    app = __import__("backend.main", fromlist=["app"]).app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await client.get("/api/documents/providers/affinda/status")
        assert status.status_code == 200 and status.json()["configured"] is True and status.json()["default_provider"] == "local"
        assert "test-affinda-secret" not in status.text and "api_key" not in status.json()
        listed = await client.get(f"/api/documents?candidate_id={owner.id}")
        assert next(item for item in listed.json() if item["id"] == document.id)["can_compare_affinda"] is True
        denied = await client.post(f"/api/documents/cv/{document.id}/provider-preview", json={"candidate_id": other.id, "provider": "affinda"})
        assert denied.status_code == 404
        response = await client.post(f"/api/documents/cv/{document.id}/provider-preview", json={"candidate_id": owner.id, "provider": "affinda"})
        assert response.status_code == 200 and response.json()["success"] is True
        assert response.json()["coverage"]["continuing_education"] == 1 and calls == 1
    async with AsyncSessionLocal() as session:
        saved = (await session.execute(select(Document).where(Document.id == document.id))).scalars().one()
    assert saved.structured_extraction == document.structured_extraction
    assert saved.confirmation_status == "confirmed" and saved.parser_version == "layout_v3" and saved.text_hash == "unchanged"


@pytest.mark.asyncio
async def test_affinda_502_parser_unavailable_has_stable_preview_failure_shape(monkeypatch):
    configured(monkeypatch)
    owner = await candidate("Affinda 502 owner")
    document = await stored_cv(owner.id)
    requests = []
    async def handler(request):
        requests.append(request)
        return httpx.Response(502, json={"error": "raw provider detail", "code": "parser_unavailable"}, headers={"retry-after": "30"})
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(documents_router.affinda_resume_parser, "_client_factory", lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs))
    app = __import__("backend.main", fromlist=["app"]).app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/documents/cv/{document.id}/provider-preview", json={"candidate_id": owner.id, "provider": "affinda"})
    body = response.json()
    assert len(requests) == 1 and response.status_code == 502
    assert body == {
        "success": False, "provider": "affinda", "upstream_status": 502,
        "code": "parser_unavailable", "provider_code": "parser_unavailable",
        "message": "Affinda parser temporarily unavailable.", "provider_message": "Affinda parser temporarily unavailable.",
        "retryable": True, "retry_after_seconds": 30,
    }
    assert "Bad Request" not in response.text and "raw provider detail" not in response.text and "test-affinda-secret" not in response.text


@pytest.mark.asyncio
async def test_affinda_preview_rejects_missing_local_file_and_configuration(monkeypatch):
    configured(monkeypatch)
    owner = await candidate("Missing Affinda PDF")
    document = await stored_cv(owner.id, local=False)
    app = __import__("backend.main", fromlist=["app"]).app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing_file = await client.post(f"/api/documents/cv/{document.id}/provider-preview", json={"candidate_id": owner.id, "provider": "affinda"})
        assert missing_file.status_code == 409 and missing_file.json()["detail"]["code"] == "stored_file_missing"
        local_document = await stored_cv(owner.id)
        monkeypatch.setattr(settings, "AFFINDA_API_KEY", "")
        unavailable = await client.post(f"/api/documents/cv/{local_document.id}/provider-preview", json={"candidate_id": owner.id, "provider": "affinda"})
        assert unavailable.status_code == 503 and unavailable.json()["code"] == "provider_not_configured" and unavailable.json()["success"] is False
