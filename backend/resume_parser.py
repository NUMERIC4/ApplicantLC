"""Small, optional resume-parser provider boundary for non-persistent previews."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import httpx

from backend.config import settings
from backend.schemas import CVCertification, CVEducation, CVLanguage, CVProfile, CVProject, CVSkill, CVWorkExperience


class ResumeParserProvider(Protocol):
    """Provider boundary intentionally limited to parsing an already-owned PDF."""

    async def parse_pdf(self, pdf: bytes, filename: str) -> "ResumeParserPreview": ...


class ResumeParserProviderError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502, *, upstream_status: int | None = None, provider_code: str | None = None, provider_message: str | None = None, retry_after_seconds: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.upstream_status = upstream_status
        self.provider_code = provider_code or code
        self.provider_message = provider_message or message
        self.retry_after_seconds = retry_after_seconds
        self.retryable = retryable


@dataclass(frozen=True)
class ResumeParserPreview:
    provider: str
    profile: CVProfile
    coverage: dict[str, int]
    coverage_gaps: list[str]
    latency_ms: int
    http_status: int
    credits_remaining: int | None
    schema_version: str | None
    classification: dict[str, Any] | None
    extraction_quality: dict[str, Any] | None


class LocalResumeParserProvider:
    """Marker for the existing local pipeline; it is not changed by this spike."""

    async def parse_pdf(self, pdf: bytes, filename: str) -> ResumeParserPreview:
        raise ResumeParserProviderError("local_preview_unsupported", "The local parser continues to use the existing CV review flow.", 409)


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def _nested_text(value: Any, *keys: str) -> str | None:
    if not isinstance(value, dict):
        return _text(value)
    for key in keys:
        text = _text(value.get(key))
        if text:
            return text
    return None


def _date(data: Any, key: str) -> str | None:
    return _text(data.get(key)) if isinstance(data, dict) else None


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _text(value)
        if item and item.casefold() not in seen:
            seen.add(item.casefold())
            result.append(item)
    return result


def _items(data: dict[str, Any], *names: str) -> list[Any]:
    for name in names:
        value = data.get(name)
        if isinstance(value, list):
            return value
    return []


def _confidence(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    normalized = float(value) / 100 if value > 1 else float(value)
    return normalized if 0 <= normalized <= 1 else None


def normalize_affinda_response(payload: dict[str, Any]) -> ResumeParserPreview:
    """Map Affinda fields deterministically; omit unsupported fields rather than infer."""
    if "data" in payload:
        raw_data = payload["data"]
    else:
        raw_data = payload
    known_fields = {"summary", "objective", "isResumeProbability", "education", "workExperience", "skills", "languages", "certifications", "projects"}
    if not isinstance(raw_data, dict) or not any(key in raw_data for key in known_fields):
        raise ResumeParserProviderError("invalid_provider_response", "Affinda returned an unexpected response format.")

    work: list[CVWorkExperience] = []
    volunteer_count = 0
    for item in _items(raw_data, "workExperience", "work_experience"):
        if not isinstance(item, dict):
            continue
        dates = item.get("dates") if isinstance(item.get("dates"), dict) else {}
        work_type = _text(item.get("type"))
        if work_type and work_type.casefold() == "volunteer":
            volunteer_count += 1
        tools = item.get("skills") if isinstance(item.get("skills"), list) else []
        work.append(CVWorkExperience(
            organization=_text(item.get("organization")),
            position=_text(item.get("jobTitle")) or _text(item.get("position")),
            location=_nested_text(item.get("location"), "rawInput", "formatted", "city"),
            start_date=_date(dates, "startDate"),
            end_date=_date(dates, "endDate"),
            description=_text(item.get("jobDescription")) or _text(item.get("description")),
            skills_or_tools=_unique_strings([_nested_text(tool, "name") for tool in tools]),
            evidence=None,
        ))

    education: list[CVEducation] = []
    for item in _items(raw_data, "education"):
        if not isinstance(item, dict):
            continue
        dates = item.get("dates") if isinstance(item.get("dates"), dict) else {}
        accreditation = item.get("accreditation")
        education.append(CVEducation(
            institution=_text(item.get("organization")) or _text(item.get("institution")),
            degree=_nested_text(accreditation, "education", "degree", "name"),
            field=_text(item.get("major")) or _text(item.get("field")),
            start_date=_date(dates, "startDate"),
            end_date=_date(dates, "completionDate") or _date(dates, "endDate"),
            status="current" if dates.get("isCurrent") is True else None,
            evidence=None,
        ))

    skills: list[CVSkill] = []
    seen_skills: set[str] = set()
    for item in _items(raw_data, "skills"):
        name = _nested_text(item, "name", "skill")
        if not name or name.casefold() in seen_skills:
            continue
        seen_skills.add(name.casefold())
        skills.append(CVSkill(name=name, category=_nested_text(item, "type", "category"), level=None, evidence=None))

    languages: list[CVLanguage] = []
    for item in _items(raw_data, "languages"):
        name = _nested_text(item, "name", "language")
        if name:
            languages.append(CVLanguage(language=name, level=_nested_text(item, "proficiency", "level"), evidence=None))

    certifications: list[CVCertification] = []
    for item in _items(raw_data, "certifications"):
        name = _nested_text(item, "name", "title", "certification")
        if name:
            certifications.append(CVCertification(name=name, issuer=_nested_text(item, "issuer", "organization"), date=_nested_text(item, "date", "issuedDate"), evidence=None))

    projects: list[CVProject] = []
    for item in _items(raw_data, "projects"):
        if not isinstance(item, dict):
            continue
        name = _nested_text(item, "title", "name")
        if name:
            projects.append(CVProject(name=name, description=_nested_text(item, "description", "projectDescription"), technologies=_unique_strings(item.get("skills") if isinstance(item.get("skills"), list) else []), evidence=None))

    training_items = _items(raw_data, "continuingEducation", "continuing_education", "courses", "training")
    coverage = {
        "skills": len(skills), "work_experience": len(work), "education": len(education),
        "languages": len(languages), "certifications": len(certifications), "projects": len(projects),
        "continuing_education": len(training_items), "volunteer_experience": volunteer_count,
    }
    gaps: list[str] = []
    if training_items:
        gaps.append("Affinda returned continuing-education/training data, but the current CV profile has no dedicated training field.")
    if volunteer_count:
        gaps.append("Affinda volunteer work is included in work experience; the current CV profile has no work-type field.")

    resume_probability = _confidence(raw_data.get("isResumeProbability"))
    classification = ({"label": "resume", "confidence": resume_probability} if resume_probability is not None else None)
    quality_value = raw_data.get("extractionQuality") or raw_data.get("extraction_quality")
    extraction_quality = quality_value if isinstance(quality_value, dict) else None
    schema_version = _text(payload.get("schemaVersion")) or _text(payload.get("schema_version"))
    profile = CVProfile(
        professional_summary=_text(raw_data.get("summary")) or _text(raw_data.get("objective")),
        skills=skills, work_experience=work, education=education, languages=languages,
        certifications=certifications, projects=projects, other_qualifications=[],
        extraction_confidence="high" if resume_probability is not None and resume_probability >= 0.85 else "medium" if resume_probability is not None else "low",
        extraction_warnings=gaps,
    )
    return ResumeParserPreview("affinda", profile, coverage, gaps, 0, 200, None, schema_version, classification, extraction_quality)


class AffindaResumeParserProvider:
    def __init__(self, client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient):
        self._client_factory = client_factory

    def configuration_status(self) -> dict[str, Any]:
        key_present = bool(settings.AFFINDA_API_KEY.strip())
        return {
            "provider": "affinda", "configured": key_present,
            "base_url": settings.AFFINDA_BASE_URL.rstrip("/"), "api_key_present": key_present,
            "default_provider": settings.RESUME_PARSER_PROVIDER,
        }

    async def parse_pdf(self, pdf: bytes, filename: str) -> ResumeParserPreview:
        if not settings.AFFINDA_API_KEY.strip():
            raise ResumeParserProviderError("provider_not_configured", "Affinda is not configured on this server.", 503)
        endpoint = f"{settings.AFFINDA_BASE_URL.rstrip('/')}/v1/resumes/parse"
        started = time.perf_counter()
        try:
            async with self._client_factory(timeout=settings.AFFINDA_REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {settings.AFFINDA_API_KEY.strip()}"},
                    # Do not disclose a candidate's original filename to the provider.
                    files={"file": ("resume.pdf", pdf, "application/pdf")},
                )
        except httpx.TimeoutException:
            raise ResumeParserProviderError("parser_timeout", "Affinda parser timed out.", 504, upstream_status=504, provider_code="parser_timeout", provider_message="Affinda parser timed out.", retryable=True) from None
        except httpx.RequestError:
            raise ResumeParserProviderError("parser_unavailable", "Affinda parser temporarily unavailable.", 503, upstream_status=503, provider_code="parser_unavailable", provider_message="Affinda parser temporarily unavailable.", retryable=True) from None

        if not response.is_success:
            raise _affinda_http_error(response)
        try:
            body = response.json()
        except ValueError:
            raise ResumeParserProviderError("invalid_provider_response", "Affinda returned invalid JSON.", upstream_status=response.status_code, provider_code="invalid_provider_response", provider_message="Affinda returned invalid JSON.") from None
        if not isinstance(body, dict):
            raise ResumeParserProviderError("invalid_provider_response", "Affinda returned an unexpected response format.", upstream_status=response.status_code, provider_code="invalid_provider_response", provider_message="Affinda returned an unexpected response format.")
        try:
            preview = normalize_affinda_response(body)
        except ResumeParserProviderError as error:
            raise ResumeParserProviderError(error.code, error.message, error.status_code, upstream_status=response.status_code, provider_code=error.code, provider_message=error.message, retryable=False) from None
        credits = response.headers.get("x-credits-remaining") or response.headers.get("credits-remaining")
        try:
            credits_remaining = int(credits) if credits is not None else None
        except ValueError:
            credits_remaining = None
        return ResumeParserPreview(
            **{**preview.__dict__, "latency_ms": round((time.perf_counter() - started) * 1000),
               "http_status": response.status_code, "credits_remaining": credits_remaining}
        )


affinda_resume_parser = AffindaResumeParserProvider()


def _safe_provider_code(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    code = value.strip().lower()
    if code and len(code) <= 80 and all(character.islower() or character.isdigit() or character in {"_", "-"} for character in code):
        return code
    return None


def _retry_after_seconds(response: httpx.Response) -> int | None:
    try:
        value = int(response.headers.get("retry-after", ""))
    except ValueError:
        return None
    return value if 0 <= value <= 86400 else None


def _affinda_http_error(response: httpx.Response) -> ResumeParserProviderError:
    """Map the documented Affinda error envelope without returning its raw text."""
    envelope: dict[str, Any] = {}
    try:
        body = response.json()
        if isinstance(body, dict):
            envelope = body
    except ValueError:
        pass
    status = response.status_code
    provider_code = _safe_provider_code(envelope.get("code"))
    defaults = {
        400: ("provider_request_invalid", "Affinda rejected this comparison request."),
        401: ("unauthorized", "Affinda authentication failed."),
        402: ("no_credits", "Affinda has no remaining credits."),
        403: ("unauthorized", "Affinda authentication failed."),
        404: ("provider_endpoint_unavailable", "The configured Affinda endpoint could not be found."),
        413: ("document_too_large", "Affinda rejected this PDF."),
        415: ("unsupported_document", "Affinda rejected this PDF."),
        422: ("unsupported_document", "Affinda could not parse this PDF."),
        429: ("rate_limited", "Affinda rate limit was reached."),
        502: ("parser_unavailable", "Affinda parser temporarily unavailable."),
        503: ("parser_unavailable", "Affinda parser temporarily unavailable."),
        504: ("parser_timeout", "Affinda parser timed out."),
    }
    default_code, message = defaults.get(status, ("provider_error", "Affinda returned an unexpected error."))
    code = provider_code or default_code
    known_messages = {
        "parser_unavailable": "Affinda parser temporarily unavailable.",
        "parser_timeout": "Affinda parser timed out.",
        "deadline": "Affinda parser timed out.",
        "unauthorized": "Affinda authentication failed.",
        "no_credits": "Affinda has no remaining credits.",
        "missing_file": "Affinda rejected this PDF.",
        "organization_required": "Affinda requires organization configuration.",
        "rate_limited": "Affinda rate limit was reached.",
    }
    message = known_messages.get(code, message)
    retryable = status == 429 or status in {502, 503, 504}
    return ResumeParserProviderError(code, message, status, upstream_status=status, provider_code=code, provider_message=message, retry_after_seconds=_retry_after_seconds(response), retryable=retryable)
