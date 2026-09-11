"""Safe, deterministic retrieval and cleanup for one user-supplied job URL."""

import asyncio
import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from backend.config import settings


MAX_RESPONSE_BYTES = 1_000_000
MAX_SOURCE_CONTEXT_CHARS = settings.JOB_SOURCE_MAX_CHARS
MAX_REDIRECTS = 3
MIN_USABLE_TEXT_CHARS = 120
IGNORED_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class JobIngestionError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class FetchedJobPage:
    source_url: str
    source_platform: str
    source_text: str
    source_text_truncated: bool
    page_title: Optional[str]
    canonical_url: Optional[str]


class _JobPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._ignored_stack: list[bool] = []
        self._text_parts: list[str] = []
        self._in_title = False
        self._title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical_url: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]):
        tag = tag.lower()
        attributes = {key.lower(): (value or "") for key, value in attrs}
        parent_ignored = any(self._ignored_stack)
        hidden = (
            "hidden" in attributes
            or attributes.get("aria-hidden", "").lower() == "true"
            or "display:none" in attributes.get("style", "").replace(" ", "").lower()
        )
        ignored = parent_ignored or tag in IGNORED_TAGS or hidden
        if tag not in VOID_TAGS:
            self._ignored_stack.append(ignored)
        if tag == "title" and not ignored:
            self._in_title = True
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            content = attributes.get("content", "").strip()
            if key and content:
                self.meta[key.lower()] = content
        if tag == "link" and "canonical" in attributes.get("rel", "").lower():
            href = attributes.get("href", "").strip()
            if href:
                self.canonical_url = href

    def handle_endtag(self, tag: str):
        if tag.lower() == "title":
            self._in_title = False
        if self._ignored_stack:
            self._ignored_stack.pop()

    def handle_data(self, data: str):
        text = " ".join(data.split())
        if not text or any(self._ignored_stack):
            return
        if self._in_title:
            self._title_parts.append(text)
        self._text_parts.append(text)

    @property
    def page_title(self) -> Optional[str]:
        title = " ".join(self._title_parts).strip()
        return title or self.meta.get("og:title") or self.meta.get("twitter:title")

    @property
    def visible_text(self) -> str:
        return "\n".join(self._text_parts)


def normalize_source_url(value: str) -> str:
    """Conservative duplicate key: casing, fragment, and root slash only."""
    try:
        parsed = urlsplit(value.strip())
    except ValueError as error:
        raise JobIngestionError("invalid_url", "The job URL is malformed.") from error
    if parsed.scheme.lower() not in {"http", "https"}:
        raise JobIngestionError("unsupported_scheme", "Only http and https job URLs are allowed.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise JobIngestionError("invalid_url", "The job URL must contain a public hostname without credentials.")
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    default_port = (parsed.scheme.lower() == "https" and port == 443) or (parsed.scheme.lower() == "http" and port == 80)
    netloc = hostname if not port or default_port else f"{hostname}:{port}"
    path = parsed.path or "/"
    if path == "/":
        path = ""
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


_normalise_url = normalize_source_url


def normalize_source_text(value: str) -> str:
    return " ".join(value.split())


def source_hash(value: str) -> str:
    """Stable SHA-256 of cleaned meaningful text, never raw page HTML."""
    return hashlib.sha256(normalize_source_text(value).encode("utf-8")).hexdigest()


def prepare_pasted_source(value: str) -> tuple[str, bool]:
    normalized = normalize_source_text(value)
    if not normalized:
        raise JobIngestionError("empty_source", "Paste the complete job advertisement before extraction.")
    if len(normalized) <= MAX_SOURCE_CONTEXT_CHARS:
        return normalized, False
    marker = " [Source text truncated]"
    return normalized[: MAX_SOURCE_CONTEXT_CHARS - len(marker)] + marker, True


def _is_public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


async def resolve_public_host(hostname: str, port: int) -> list[str]:
    """Resolve a hostname and reject every non-global address it returns."""
    try:
        direct_ip = ipaddress.ip_address(hostname)
        addresses = [str(direct_ip)]
    except ValueError:
        try:
            records = await asyncio.to_thread(
                socket.getaddrinfo,
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as error:
            raise JobIngestionError("dns_failure", "The job URL hostname could not be resolved.") from error
        addresses = list({record[4][0] for record in records})

    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise JobIngestionError("private_target", "The job URL resolves to a private or internal network target.")
    return addresses


async def _validate_public_url(value: str) -> tuple[str, str]:
    normalised = normalize_source_url(value)
    parsed = urlsplit(normalised)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    try:
        if not ipaddress.ip_address(hostname).is_global:
            raise JobIngestionError("private_target", "The job URL targets a private or internal IP address.")
    except ValueError:
        pass
    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
        or hostname.endswith(".internal")
        or hostname.endswith(".lan")
        or "." not in hostname
    ):
        raise JobIngestionError("private_target", "Local or internal job URLs are not allowed.")
    await resolve_public_host(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    return normalised, hostname


def _build_source_context(parser: _JobPageParser) -> tuple[str, bool]:
    visible_text = parser.visible_text.strip()
    metadata_parts = []
    if parser.page_title:
        metadata_parts.append(f"Page title: {parser.page_title}")
    description = parser.meta.get("description") or parser.meta.get("og:description")
    if description:
        metadata_parts.append(f"Page description: {description}")
    combined = "\n".join([*metadata_parts, visible_text]).strip()
    if len(combined) <= MAX_SOURCE_CONTEXT_CHARS:
        return combined, False

    # Preserve the document opening and a later qualifications/responsibilities
    # section instead of blindly passing only a huge page header to the model.
    lower = combined.lower()
    anchors = ("requirements", "qualifications", "responsibilities", "what you bring", "your profile")
    anchor_index = next((lower.find(anchor) for anchor in anchors if lower.find(anchor) >= 0), -1)
    opening = combined[: MAX_SOURCE_CONTEXT_CHARS // 2]
    if anchor_index < 0:
        return opening + "\n[Source text truncated]", True
    remaining = MAX_SOURCE_CONTEXT_CHARS - len(opening) - len("\n[Source text truncated]\n")
    start = max(0, anchor_index - remaining // 4)
    return opening + "\n[Source text truncated]\n" + combined[start:start + remaining], True


async def _fetch_with_client(client: httpx.AsyncClient, initial_url: str) -> FetchedJobPage:
    current_url = initial_url
    for redirect_count in range(MAX_REDIRECTS + 1):
        current_url, hostname = await _validate_public_url(current_url)
        try:
            async with client.stream(
                "GET",
                current_url,
                headers={"User-Agent": "ApplicantLC Job Preview/1.0"},
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise JobIngestionError("fetch_error", "The job page returned an invalid redirect.", 502)
                    if redirect_count >= MAX_REDIRECTS:
                        raise JobIngestionError("too_many_redirects", "The job page redirected too many times.", 422)
                    current_url = urljoin(current_url, location)
                    continue
                if response.status_code >= 400:
                    raise JobIngestionError(
                        "http_error",
                        f"The job page returned HTTP {response.status_code}.",
                        502,
                    )
                content_type = response.headers.get("content-type", "").lower()
                if content_type and "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                    raise JobIngestionError("unsupported_content", "The job URL did not return an HTML page.")
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > MAX_RESPONSE_BYTES:
                            raise JobIngestionError("response_too_large", "The job page is too large to process safely.")
                    except ValueError:
                        pass

                chunks: list[bytes] = []
                received = 0
                async for chunk in response.aiter_bytes():
                    received += len(chunk)
                    if received > MAX_RESPONSE_BYTES:
                        raise JobIngestionError("response_too_large", "The job page is too large to process safely.")
                    chunks.append(chunk)
                html = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        except httpx.TimeoutException:
            raise JobIngestionError("fetch_timeout", "Fetching the job page timed out.", 504) from None
        except httpx.HTTPError:
            raise JobIngestionError("fetch_error", "The job page could not be fetched.", 502) from None

        parser = _JobPageParser()
        parser.feed(html)
        parser.close()
        source_text, truncated = _build_source_context(parser)
        lower_source = source_text.lower()
        if any(marker in lower_source for marker in ("captcha", "access denied", "unusual traffic")):
            raise JobIngestionError("anti_bot_page", "The job page appears to be protected by an anti-bot page.")
        if len(parser.visible_text.strip()) < MIN_USABLE_TEXT_CHARS:
            raise JobIngestionError(
                "unusable_page",
                "Page content could not be extracted reliably. The site may require JavaScript rendering.",
            )
        canonical = urljoin(current_url, parser.canonical_url) if parser.canonical_url else None
        return FetchedJobPage(
            source_url=current_url,
            source_platform=hostname,
            source_text=source_text,
            source_text_truncated=truncated,
            page_title=parser.page_title,
            canonical_url=canonical,
        )

    raise JobIngestionError("too_many_redirects", "The job page redirected too many times.")


async def fetch_job_page(url: str, client: Optional[httpx.AsyncClient] = None) -> FetchedJobPage:
    """Fetch exactly one public HTML page with bounded redirects and bytes."""
    if client is not None:
        return await _fetch_with_client(client, url)
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as owned_client:
        return await _fetch_with_client(owned_client, url)
