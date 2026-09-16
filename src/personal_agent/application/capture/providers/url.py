from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError

from personal_agent.kernel.config import Settings
from personal_agent.application.capture.models import UrlCaptureResult
from personal_agent.application.capture.web_source import MAX_URL_RESPONSE_BYTES
from personal_agent.application.capture.utils import extract_html_text
from personal_agent.application.capture.providers.base import UrlCaptureProvider


class _FirecrawlData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    markdown: str


class _FirecrawlResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: _FirecrawlData


def _read_response(response) -> bytes:
    body = response.read(MAX_URL_RESPONSE_BYTES + 1)
    if len(body) > MAX_URL_RESPONSE_BYTES:
        raise HTTPException(status_code=413, detail="网页响应超过 4 MiB 容量，未交付正文。")
    return body


class FirecrawlUrlCaptureProvider(UrlCaptureProvider):
    name = "firecrawl"

    def __init__(self, settings: Settings, logger: logging.Logger | None = None) -> None:
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)

    def can_handle(self, url: str) -> bool:
        return bool(self.settings.firecrawl.api_key)

    def capture(self, url: str) -> UrlCaptureResult:
        base_url = self.settings.firecrawl.base_url.rstrip("/")
        payload = {
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": True,
        }
        request = Request(
            f"{base_url}/v2/scrape",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.firecrawl.api_key}",
            },
            method="POST",
        )
        timeout_seconds = max(5, self.settings.firecrawl.timeout_ms / 1000)
        self.logger.info("Firecrawl scrape requested url=%s base_url=%s", url, base_url)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = _read_response(response)
        except HTTPError as exc:
            detail = exc.read(240).decode("utf-8", errors="replace") if getattr(exc, "fp", None) else ""
            raise HTTPException(
                status_code=400,
                detail=f"Firecrawl scrape failed: HTTP {exc.code}{f' - {detail[:240]}' if detail else ''}",
            ) from exc
        except URLError as exc:
            raise HTTPException(status_code=400, detail=f"Firecrawl scrape failed: {exc.reason}") from exc

        try:
            captured = _FirecrawlResponse.model_validate_json(raw)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail="Firecrawl returned invalid JSON.") from exc

        markdown = captured.data.markdown
        if not markdown.strip():
            raise HTTPException(status_code=400, detail="Firecrawl did not return readable markdown content.")

        return UrlCaptureResult(url=url, text=markdown, provider=self.name)


class BuiltinUrlCaptureProvider(UrlCaptureProvider):
    name = "builtin"

    def can_handle(self, url: str) -> bool:
        return True

    def capture(self, url: str) -> UrlCaptureResult:
        request = Request(
            url,
            headers={
                "User-Agent": "personal-agent/0.1 (+https://local.agent)",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
            },
        )
        try:
            with urlopen(request, timeout=12) as response:
                body = _read_response(response)
                content_type = response.headers.get_content_type()
                charset = response.headers.get_content_charset() or "utf-8"
        except HTTPError as exc:
            raise HTTPException(status_code=400, detail=f"Failed to fetch URL: HTTP {exc.code}") from exc
        except URLError as exc:
            raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {exc.reason}") from exc

        text = body.decode(charset, errors="replace")
        if content_type in {"text/plain", "text/markdown"}:
            if not text.strip():
                raise HTTPException(status_code=400, detail="The URL returned an empty text document.")
            return UrlCaptureResult(url=url, text=text, provider=self.name)

        extracted = extract_html_text(text)
        if not extracted:
            raise HTTPException(status_code=400, detail="No readable text content could be extracted from the URL.")
        return UrlCaptureResult(url=url, text=extracted, provider=self.name)
