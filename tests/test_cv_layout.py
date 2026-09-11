import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select

from backend.cv_ingestion import extract_pdf_text
from backend.cv_layout import LayoutExtractionError, reconstruct_pdf
from backend.database import AsyncSessionLocal, init_db
from backend.models import Candidate, Document
from backend.routers import documents as documents_router
from backend.schemas import CVExtractionServiceResult, CVProfile


def positioned_pdf(pages: list[list[tuple[float, float, float, str]]]) -> bytes:
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")}))
    for entries in pages:
        page = writer.add_blank_page(612, 792)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        operations = []
        for x, y, size, text in entries:
            safe = text.replace("(", "[").replace(")", "]")
            operations.append(f"BT /F1 {size} Tf {x} {y} Td ({safe}) Tj ET")
        stream.set_data("\n".join(operations).encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def fixture_pdf() -> bytes:
    return positioned_pdf([[
        (72, 750, 16, "EDUCATION"),
        (72, 700, 11, "2023-present"), (240, 700, 11, "Example University"), (240, 682, 11, "B.Sc. Computer Science"),
        (72, 635, 16, "PROJECTS"),
        (72, 590, 11, "2024"), (240, 590, 11, "Inventory Dashboard"), (240, 572, 11, "Built with Python"),
        (72, 530, 11, "2023"), (240, 530, 11, "Network Tool"), (240, 512, 11, "Built with C++"),
    ]])


def cv_profile() -> CVProfile:
    return CVProfile(professional_summary=None, skills=[], work_experience=[], education=[], languages=[], certifications=[], projects=[], other_qualifications=[], extraction_confidence="medium", extraction_warnings=[])


@pytest.mark.asyncio
async def test_geometry_reconstruction_preserves_rows_sections_blocks_and_pages():
    result = reconstruct_pdf(fixture_pdf())
    assert result.parser_version == "layout_v3" and result.metadata["fallback_used"] is False
    assert "[SECTION" in result.model_text and "EDUCATION" in result.model_text and "PROJECTS" in result.model_text
    assert "[ROW" in result.model_text and "2023-present" in result.model_text and "Example University" in result.model_text
    assert result.model_text.count("Inventory Dashboard") == 1
    assert result.model_text.count("Network Tool") == 1
    multi = reconstruct_pdf(positioned_pdf([[(72, 700, 12, "Page One sufficient text for generic reconstruction validation")], [(72, 700, 12, "Page Two remains after Page One in reading order validation")]]))
    assert multi.model_text.index("[PAGE 1]") < multi.model_text.index("[PAGE 2]")


def test_generic_nested_line_rows_keep_aligned_pairs_and_distinct_entries():
    result = reconstruct_pdf(positioned_pdf([[
        (72, 750, 16, "DETAILS"),
        (72, 700, 11, "Label One"), (240, 700, 11, "Value One"),
        (72, 682, 11, "Label Two"), (240, 682, 11, "Value Two"),
        (72, 630, 11, "2024"), (240, 630, 11, "First Item"),
        (72, 612, 11, "2023"), (240, 612, 11, "Second Item"),
        (72, 560, 11, "Course A"), (240, 560, 11, "Provider A"),
        (72, 542, 11, "Course B"), (240, 542, 11, "Provider B"),
    ]]))
    assert result.model_text.count("[LINE_ROW ") >= 6
    for left, right in (("Label One", "Value One"), ("Label Two", "Value Two"), ("2024", "First Item"), ("2023", "Second Item"), ("Course A", "Provider A"), ("Course B", "Provider B")):
        start = result.model_text.index(left)
        end = result.model_text.index("[/LINE_ROW]", start)
        assert right in result.model_text[start:end]


@pytest.mark.asyncio
async def test_layout_fallback_is_explicit(monkeypatch):
    import backend.cv_ingestion as ingestion
    monkeypatch.setattr(ingestion, "reconstruct_pdf", lambda _data: (_ for _ in ()).throw(LayoutExtractionError("no geometry")))
    result = extract_pdf_text(fixture_pdf())
    assert result.parser_version == "linear_v1"
    assert result.layout_metadata["fallback_used"] is True
    assert result.warnings


async def _candidate() -> Candidate:
    await init_db()
    async with AsyncSessionLocal() as session:
        candidate = Candidate(profile_name="Layout Reprocess Candidate")
        session.add(candidate)
        await session.commit()
        await session.refresh(candidate)
        return candidate


@pytest.mark.asyncio
async def test_legacy_duplicate_offers_reprocess_and_reprocesses_one_unconfirmed_document(monkeypatch):
    candidate = await _candidate()
    calls = 0
    async def fake_extract(_text):
        nonlocal calls
        calls += 1
        return CVExtractionServiceResult(profile=cv_profile(), latency_ms=1, usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, response_format_json=True, thinking_disabled=True)
    monkeypatch.setattr(documents_router.ai_service, "extract_cv_profile", fake_extract)
    app = __import__("backend.main", fromlist=["app"]).app
    pdf = fixture_pdf()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/documents/cv/upload", data={"candidate_id": str(candidate.id)}, files={"file": ("layout.pdf", pdf, "application/pdf")})
        assert first.status_code == 200
        document_id = first.json()["document"]["id"]
        async with AsyncSessionLocal() as session:
            document = (await session.execute(select(Document).where(Document.id == document_id))).scalars().one()
            document.parser_version = "linear_v1"
            await session.commit()
        duplicate = await client.post("/api/documents/cv/upload", data={"candidate_id": str(candidate.id)}, files={"file": ("layout.pdf", pdf, "application/pdf")})
        assert duplicate.json()["state"] == "duplicate" and duplicate.json()["reprocess_available"] is True
        before_count = (await client.get(f"/api/documents/cv/{document_id}?candidate_id={candidate.id}")).json()["document"]["id"]
        reprocessed = await client.post(f"/api/documents/cv/{document_id}/reprocess", json={"candidate_id": candidate.id})
        assert reprocessed.status_code == 200 and reprocessed.json()["document"]["id"] == before_count
        assert reprocessed.json()["document"]["confirmation_status"] == "unconfirmed"
        assert reprocessed.json()["document"]["parser_version"] == "layout_v3"
        confirm = await client.post(f"/api/documents/cv/{document_id}/confirm", json={"candidate_id": candidate.id, "profile": cv_profile().model_dump(mode="json")})
        assert confirm.status_code == 200
        blocked = await client.post(f"/api/documents/cv/{document_id}/reprocess", json={"candidate_id": candidate.id})
        assert blocked.status_code == 409
    assert calls == 2  # initial extraction + exactly one explicit reprocess
    async with AsyncSessionLocal() as session:
        document = (await session.execute(select(Document).where(Document.id == document_id))).scalars().one()
        assert Path(document.stored_path).is_file()


@pytest.mark.asyncio
async def test_reprocess_rejects_a_concurrent_request_and_releases_its_in_memory_lock(monkeypatch):
    candidate = await _candidate()
    async def initial_extract(_text):
        return CVExtractionServiceResult(profile=cv_profile(), latency_ms=1, usage={}, response_format_json=True, thinking_disabled=True)
    monkeypatch.setattr(documents_router.ai_service, "extract_cv_profile", initial_extract)
    app = __import__("backend.main", fromlist=["app"]).app
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def slow_extract(_text):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return CVExtractionServiceResult(profile=cv_profile(), latency_ms=1, usage={}, response_format_json=True, thinking_disabled=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post("/api/documents/cv/upload", data={"candidate_id": str(candidate.id)}, files={"file": ("concurrent.pdf", fixture_pdf(), "application/pdf")})
        document_id = uploaded.json()["document"]["id"]
        monkeypatch.setattr(documents_router.ai_service, "extract_cv_profile", slow_extract)
        first = asyncio.create_task(client.post(f"/api/documents/cv/{document_id}/reprocess", json={"candidate_id": candidate.id}))
        await asyncio.wait_for(entered.wait(), timeout=1)
        second = await client.post(f"/api/documents/cv/{document_id}/reprocess", json={"candidate_id": candidate.id})
        assert second.status_code == 409 and second.json()["detail"]["code"] == "already_processing"
        release.set()
        assert (await first).status_code == 200
    assert calls == 1
