from types import SimpleNamespace

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from backend.ai_service import JobExtractionServiceError, ai_service
from backend.database import AsyncSessionLocal, init_db
from backend.job_ingestion import FetchedJobPage, JobIngestionError, fetch_job_page, normalize_source_url, source_hash
from backend.models import Company, Job, JobRequirement
from backend.routers import jobs as jobs_router
from backend.schemas import JobExtractionPreview, JobExtractionRequirement, JobExtractionServiceResult


VALID_HTML = b"""
<html><head>
  <title>Software Engineering Intern | Example Robotics</title>
  <meta name="description" content="Backend internship in Essen">
  <style>.secret { display: none; } CSS_SHOULD_NOT_APPEAR</style>
  <script>window.prompt = 'SCRIPT_SHOULD_NOT_APPEAR';</script>
</head><body>
  <nav>Navigation links that are not job data</nav>
  <main>
    <h1>Software Engineering Intern</h1>
    <p>Example Robotics GmbH is hiring in Essen, Germany.</p>
    <p>Required qualifications: Python and Git.</p>
    <p>Preferred qualifications: Docker.</p>
    <p>The internship focuses on backend software development and reliable services.</p>
  </main>
  <footer>Cookie preferences</footer>
</body></html>
"""


async def _public_resolver(_hostname: str, _port: int) -> list[str]:
    return ["93.184.216.34"]


def _html_client(handler) -> AsyncClient:
    return AsyncClient(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(1.0))


@pytest.mark.asyncio
async def test_fetch_extracts_visible_job_content_and_drops_script_and_style(monkeypatch):
    monkeypatch.setattr("backend.job_ingestion.resolve_public_host", _public_resolver)

    async def handler(_request):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=VALID_HTML)

    async with _html_client(handler) as client:
        page = await fetch_job_page("https://jobs.example.test/intern", client=client)

    assert page.page_title == "Software Engineering Intern | Example Robotics"
    assert "Required qualifications: Python and Git." in page.source_text
    assert "SCRIPT_SHOULD_NOT_APPEAR" not in page.source_text
    assert "CSS_SHOULD_NOT_APPEAR" not in page.source_text
    assert "Navigation links" not in page.source_text


@pytest.mark.asyncio
@pytest.mark.parametrize("url, code", [
    ("not a url", "unsupported_scheme"),
    ("ftp://jobs.example.test/opening", "unsupported_scheme"),
    ("http://localhost:8000/job", "private_target"),
    ("http://127.0.0.1/job", "private_target"),
    ("http://10.0.0.8/job", "private_target"),
])
async def test_invalid_or_internal_urls_are_rejected_without_fetch(url, code):
    async def handler(_request):
        raise AssertionError("network must not be called")

    async with _html_client(handler) as client:
        with pytest.raises(JobIngestionError) as error:
            await fetch_job_page(url, client=client)
    assert error.value.code == code


@pytest.mark.asyncio
async def test_redirect_to_private_target_is_rejected(monkeypatch):
    monkeypatch.setattr("backend.job_ingestion.resolve_public_host", _public_resolver)

    async def handler(_request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    async with _html_client(handler) as client:
        with pytest.raises(JobIngestionError) as error:
            await fetch_job_page("https://jobs.example.test/opening", client=client)
    assert error.value.code == "private_target"


@pytest.mark.asyncio
async def test_fetch_failures_and_unusable_pages_are_controlled(monkeypatch):
    monkeypatch.setattr("backend.job_ingestion.resolve_public_host", _public_resolver)

    async def timeout_handler(_request):
        raise httpx.ReadTimeout("timeout")

    async with _html_client(timeout_handler) as client:
        with pytest.raises(JobIngestionError) as timeout_error:
            await fetch_job_page("https://jobs.example.test/opening", client=client)
    assert timeout_error.value.code == "fetch_timeout"

    async def status_handler(_request):
        return httpx.Response(503, headers={"content-type": "text/html"})

    async with _html_client(status_handler) as client:
        with pytest.raises(JobIngestionError) as status_error:
            await fetch_job_page("https://jobs.example.test/opening", client=client)
    assert status_error.value.code == "http_error"

    async def empty_handler(_request):
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html><body>Hi</body></html>")

    async with _html_client(empty_handler) as client:
        with pytest.raises(JobIngestionError) as empty_error:
            await fetch_job_page("https://jobs.example.test/opening", client=client)
    assert empty_error.value.code == "unusable_page"


@pytest.mark.asyncio
async def test_structured_extraction_validates_output_and_uses_json_mode(monkeypatch):
    captured = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='''{
                    "company_name":"Example Robotics GmbH",
                    "position_title":"Software Engineering Intern",
                    "location":"Essen, Germany",
                    "job_description":"Backend internship.",
                    "required_qualifications":[{"text":"Python","category":"Technical","importance":"required","source_evidence":"Python is required."}],
                    "preferred_qualifications":[],
                    "source_url":"https://wrong.example",
                    "source_platform":null,
                    "evidence_confidence":"high"
                }'''))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            )

    monkeypatch.setattr(ai_service, "_get_client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())))
    ai_service.api_key = "mocked-key"
    result = await ai_service.extract_job_structured(
        source_url="https://jobs.example.test/opening",
        source_text="Example Robotics GmbH requires Python.",
        source_platform="jobs.example.test",
    )

    assert result.preview.company_name == "Example Robotics GmbH"
    assert result.preview.source_url == "https://jobs.example.test/opening"
    assert result.usage["total_tokens"] == 30
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert captured["temperature"] == 0


@pytest.mark.asyncio
async def test_structured_extraction_keeps_missing_fields_empty_and_rejects_invalid_json(monkeypatch):
    class EmptyFactsCompletions:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
                usage=None,
            )

    monkeypatch.setattr(ai_service, "_get_client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=EmptyFactsCompletions())))
    ai_service.api_key = "mocked-key"
    result = await ai_service.extract_job_structured(
        source_url="https://jobs.example.test/opening", source_text="Only source text."
    )
    assert result.preview.company_name is None
    assert result.preview.required_qualifications == []

    class InvalidCompletions:
        async def create(self, **_kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))], usage=None)

    monkeypatch.setattr(ai_service, "_get_client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=InvalidCompletions())))
    with pytest.raises(JobExtractionServiceError) as error:
        await ai_service.extract_job_structured(
            source_url="https://jobs.example.test/opening", source_text="Only source text."
        )
    assert error.value.code == "invalid_ai_output"


@pytest.mark.asyncio
async def test_provider_failure_is_explicit_and_never_calls_legacy_heuristic(monkeypatch):
    class FailingCompletions:
        async def create(self, **_kwargs):
            raise RuntimeError("provider internals")

    def legacy_method_must_not_run(*_args, **_kwargs):
        raise AssertionError("legacy heuristic must not be called")

    monkeypatch.setattr(ai_service, "_get_client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=FailingCompletions())))
    monkeypatch.setattr(ai_service, "_heuristic_evaluate_fit", legacy_method_must_not_run)
    ai_service.api_key = "mocked-key"
    with pytest.raises(JobExtractionServiceError) as error:
        await ai_service.extract_job_structured(
            source_url="https://jobs.example.test/opening", source_text="Only source text."
        )
    assert error.value.code == "provider_error"


@pytest.mark.asyncio
async def test_ingestion_preview_is_transient_and_confirmation_persists_user_edits(monkeypatch):
    await init_db()
    # The repository's SQLite test database is reused between runs; clear only
    # this legacy fixture URL so it continues testing the new-URL path.
    async with AsyncSessionLocal() as session:
        existing_ids = select(Job.id).where(Job.source_url == "https://jobs.example.test/opening")
        await session.execute(delete(JobRequirement).where(JobRequirement.job_id.in_(existing_ids)))
        await session.execute(delete(Job).where(Job.id.in_(existing_ids)))
        await session.commit()
    preview = JobExtractionPreview(
        company_name="Incorrect AI Company AG",
        position_title="AI Extracted Title",
        location=None,
        job_description="AI draft description",
        required_qualifications=[
            {"text": "Python", "category": "Technical", "importance": "required", "source_evidence": "Python is required."},
            {"text": "Removed Requirement", "category": None, "importance": "required", "source_evidence": "Not retained by user."},
        ],
        preferred_qualifications=[
            {"text": "Docker", "category": "Technical", "importance": "preferred", "source_evidence": "Docker is preferred."},
        ],
        source_url="https://jobs.example.test/opening",
        source_platform="jobs.example.test",
        evidence_confidence="medium",
    )
    page = FetchedJobPage(
        source_url="https://jobs.example.test/opening",
        source_platform="jobs.example.test",
        source_text="Example source text with Python and Docker.",
        source_text_truncated=False,
        page_title="Test Job",
        canonical_url=None,
    )
    extraction = JobExtractionServiceResult(
        preview=preview,
        latency_ms=1,
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        response_format_json=True,
        thinking_disabled=True,
    )

    async def fake_fetch(_url):
        return page

    async def fake_extract(**_kwargs):
        return extraction

    monkeypatch.setattr(jobs_router, "fetch_job_page", fake_fetch)
    monkeypatch.setattr(jobs_router.ai_service, "extract_job_structured", fake_extract)

    async with AsyncSessionLocal() as session:
        companies_before = (await session.execute(select(func.count(Company.id)))).scalar_one()

    async with AsyncClient(transport=ASGITransport(app=__import__("backend.main", fromlist=["app"]).app), base_url="http://test") as client:
        ingest_response = await client.post("/api/jobs/ingest", json={"url": "https://jobs.example.test/opening"})
        assert ingest_response.status_code == 200
        assert ingest_response.json()["preview"]["company_name"] == "Incorrect AI Company AG"

        async with AsyncSessionLocal() as session:
            companies_after_preview = (await session.execute(select(func.count(Company.id)))).scalar_one()
        assert companies_after_preview == companies_before

        confirmation = {
            "company_name": "Corrected Robotics GmbH",
            "position_title": "Corrected Backend Intern",
            "source_url": "https://jobs.example.test/opening",
            "location": "Essen, Germany",
            "job_description": "User-reviewed description.",
            "source_platform": "jobs.example.test",
            "source_text": page.source_text,
            "required_qualifications": [
                {"text": "Python", "category": "Technical", "importance": "required", "source_evidence": "Python is required."},
                {"text": "SQL", "category": "Technical", "importance": "required", "source_evidence": None},
            ],
            "preferred_qualifications": [
                {"text": "Docker", "category": "Technical", "importance": "preferred", "source_evidence": "Docker is preferred."},
                {"text": "Python", "category": "Technical", "importance": "preferred", "source_evidence": "Duplicate must not persist."},
            ],
        }
        confirm_response = await client.post("/api/jobs/confirm", json=confirmation)
        assert confirm_response.status_code == 200
        confirmed = confirm_response.json()
        assert confirmed["company"]["name"] == "Corrected Robotics GmbH"
        assert confirmed["job"]["title"] == "Corrected Backend Intern"
        assert {item["requirement"] for item in confirmed["requirements"]} == {"Python", "SQL", "Docker"}

        reused = await client.post("/api/jobs/confirm", json={**confirmation, "company_name": "corrected robotics gmbh"})
        assert reused.status_code == 200
        assert reused.json()["company"]["id"] == confirmed["company"]["id"]

    async with AsyncSessionLocal() as session:
        saved_job = (await session.execute(
            select(Job).where(Job.title == "Corrected Backend Intern").order_by(Job.id.desc())
        )).scalars().first()
        requirements = (await session.execute(
            select(JobRequirement).where(JobRequirement.job_id == saved_job.id)
        )).scalars().all()
    assert saved_job.confirmation_status == "confirmed"
    assert "Removed Requirement" not in {item.requirement for item in requirements}
    assert "SQL" in {item.requirement for item in requirements}


async def _confirmed_job(url: str, text: str, title: str = "Versioned Intern") -> Job:
    await init_db()
    async with AsyncSessionLocal() as session:
        company = Company(name=f"Versioned {title} GmbH")
        session.add(company)
        await session.flush()
        job = Job(
            company_id=company.id, title=title, source_url=url,
            normalized_source_url=normalize_source_url(url), source_hash=source_hash(text),
            raw_source_text=text, confirmation_status="confirmed", version_number=1,
            version_source="imported",
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job


@pytest.mark.asyncio
async def test_duplicate_normalization_and_open_existing_use_no_fetch_or_ai(monkeypatch):
    job = await _confirmed_job("https://jobs.example.test/duplicate", "original source", "Duplicate URL")

    async def never_fetch(_url):
        raise AssertionError("duplicate lookup must not fetch")

    async def never_extract(**_kwargs):
        raise AssertionError("duplicate lookup must not call NVIDIA")

    monkeypatch.setattr(jobs_router, "fetch_job_page", never_fetch)
    monkeypatch.setattr(jobs_router.ai_service, "extract_job_structured", never_extract)
    async with AsyncClient(transport=ASGITransport(app=__import__("backend.main", fromlist=["app"]).app), base_url="http://test") as client:
        response = await client.post("/api/jobs/ingest", json={"url": "HTTPS://JOBS.EXAMPLE.TEST/duplicate#ignored"})
        assert response.status_code == 200
        assert response.json()["state"] == "duplicate"
        assert response.json()["latest_job"]["id"] == job.id
        opened = await client.get(f"/api/jobs/{job.id}")
        assert opened.status_code == 200
        assert opened.json()["job"]["id"] == job.id


@pytest.mark.asyncio
async def test_unchanged_update_skips_nvidia_and_changed_preview_is_transient(monkeypatch):
    url = "https://jobs.example.test/unchanged"
    old = await _confirmed_job(url, "same cleaned source", "Unchanged URL")
    page = FetchedJobPage(url, "jobs.example.test", "same cleaned source", False, None, None)

    async def fake_fetch(_url):
        return page

    async def never_extract(**_kwargs):
        raise AssertionError("unchanged source must not call NVIDIA")

    monkeypatch.setattr(jobs_router, "fetch_job_page", fake_fetch)
    monkeypatch.setattr(jobs_router.ai_service, "extract_job_structured", never_extract)
    async with AsyncClient(transport=ASGITransport(app=__import__("backend.main", fromlist=["app"]).app), base_url="http://test") as client:
        unchanged = await client.post("/api/jobs/check-update", json={"url": url})
        assert unchanged.status_code == 200
        assert unchanged.json()["state"] == "unchanged"

        page_changed = FetchedJobPage(url, "jobs.example.test", "changed cleaned source", False, None, None)
        async def changed_fetch(_url): return page_changed
        preview = JobExtractionPreview(company_name="Versioned Unchanged URL GmbH", position_title="Changed Title")
        async def changed_extract(**_kwargs):
            return JobExtractionServiceResult(preview=preview, latency_ms=1, usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, response_format_json=True, thinking_disabled=True)
        monkeypatch.setattr(jobs_router, "fetch_job_page", changed_fetch)
        monkeypatch.setattr(jobs_router.ai_service, "extract_job_structured", changed_extract)
        changed = await client.post("/api/jobs/check-update", json={"url": url})
        assert changed.status_code == 200
        assert changed.json()["existing_job_id"] == old.id
    async with AsyncSessionLocal() as session:
        versions = list((await session.execute(select(Job).where(Job.id == old.id))).scalars())
    assert len(versions) == 1  # Closing/cancelling this preview has no persistence effect.


@pytest.mark.asyncio
async def test_confirmed_update_and_manual_edit_create_immutable_versions_without_ai():
    url = "https://jobs.example.test/version-chain"
    old = await _confirmed_job(url, "version one source", "Version Chain")
    update_source = "version two source"
    async with AsyncClient(transport=ASGITransport(app=__import__("backend.main", fromlist=["app"]).app), base_url="http://test") as client:
        update = await client.post("/api/jobs/confirm", json={
            "company_name": "Versioned Version Chain GmbH", "position_title": "Version Two", "source_url": url,
            "source_text": update_source, "version_source": "source_update", "supersedes_job_id": old.id,
            "source_hash": source_hash(update_source), "required_qualifications": [{"text": "Python", "category": "Technical", "importance": "required"}],
        })
        assert update.status_code == 200
        second = update.json()["job"]
        assert second["version_number"] == 2 and second["supersedes_job_id"] == old.id
        manual = await client.post(f"/api/jobs/{second['id']}/manual-version", json={
            "company_name": "Versioned Version Chain GmbH", "position_title": "Manual Corrected", "job_description": "Reviewed manually",
            "required_qualifications": [{"text": "Python", "category": "Technical", "importance": "required"}],
        })
        assert manual.status_code == 200
        third = manual.json()["job"]
        assert third["version_number"] == 3 and third["supersedes_job_id"] == second["id"]
        assert third["version_source"] == "manual_correction"
        latest = await client.post("/api/jobs/ingest", json={"url": url})
        assert latest.json()["latest_job"]["id"] == third["id"]
    async with AsyncSessionLocal() as session:
        historical = (await session.execute(select(Job).where(Job.id == old.id))).scalars().one()
    assert historical.title == "Version Chain" and historical.version_number == 1


@pytest.mark.asyncio
async def test_pasted_text_uses_same_mocked_extraction_and_requires_no_url(monkeypatch):
    long_text = ("Example Paste GmbH seeks a Backend Intern with Python and German B2. " * 500)
    preview = JobExtractionPreview(company_name="Example Paste GmbH", position_title="Backend Intern", required_qualifications=[{"text": "Python", "category": "Technical", "importance": "required"}])
    calls = 0
    async def fake_extract(**kwargs):
        nonlocal calls
        calls += 1
        assert kwargs["source_url"] == ""
        return JobExtractionServiceResult(preview=preview, latency_ms=1, usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, response_format_json=True, thinking_disabled=True)
    monkeypatch.setattr(jobs_router.ai_service, "extract_job_structured", fake_extract)
    async with AsyncClient(transport=ASGITransport(app=__import__("backend.main", fromlist=["app"]).app), base_url="http://test") as client:
        extracted = await client.post("/api/jobs/extract-text", json={"text": long_text})
        assert extracted.status_code == 200 and extracted.json()["preview"]["source_url"] is None
        confirmed = await client.post("/api/jobs/confirm", json={
            "company_name": "Example Paste GmbH", "position_title": "Backend Intern", "source_url": None,
            "source_text": extracted.json()["source_text"], "version_source": "pasted_text",
            "required_qualifications": [{"text": "Python", "category": "Technical", "importance": "required"}],
        })
        assert confirmed.status_code == 200
        assert confirmed.json()["job"]["version_number"] == 1
        assert confirmed.json()["job"]["version_source"] == "pasted_text"
    assert calls == 1
    assert JobExtractionRequirement(text="Unknown category", category="Not mapped", importance="required").category == "Other"
