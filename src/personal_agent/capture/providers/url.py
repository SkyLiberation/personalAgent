from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException

from ...core.config import Settings
from ..models import UrlCaptureResult
from ..utils import extract_html_text
from .base import UrlCaptureProvider


class FirecrawlUrlCaptureProvider(UrlCaptureProvider):
    name = "firecrawl"

    def __init__(self, settings: Settings, logger: logging.Logger | None = None) -> None:
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)

    def can_handle(self, url: str) -> bool:
        return bool(self.settings.firecrawl_api_key)

    def capture(self, url: str) -> UrlCaptureResult:
        base_url = self.settings.firecrawl_base_url.rstrip("/")
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
                "Authorization": f"Bearer {self.settings.firecrawl_api_key}",
            },
            method="POST",
        )
        timeout_seconds = max(5, self.settings.firecrawl_timeout_ms / 1000)
        self.logger.info("Firecrawl scrape requested url=%s base_url=%s", url, base_url)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if getattr(exc, "fp", None) else ""
            raise HTTPException(
                status_code=400,
                detail=f"Firecrawl scrape failed: HTTP {exc.code}{f' - {detail[:240]}' if detail else ''}",
            ) from exc
        except URLError as exc:
            raise HTTPException(status_code=400, detail=f"Firecrawl scrape failed: {exc.reason}") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Firecrawl returned invalid JSON.") from exc

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Firecrawl returned an unexpected response shape.")

        markdown = str(data.get("markdown") or "").strip()
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        title = str(metadata.get("title") or "").strip()

        if not markdown:
            raise HTTPException(status_code=400, detail="Firecrawl did not return readable markdown content.")

        heading = f"Captured URL: {url}"
        if title:
            heading = f"Captured URL: {title}\nSource: {url}"
        return UrlCaptureResult(text=f"{heading}\n\n{markdown[:12000]}", provider=self.name)


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
                body = response.read()
                content_type = response.headers.get_content_type()
                charset = response.headers.get_content_charset() or "utf-8"
        except HTTPError as exc:
            raise HTTPException(status_code=400, detail=f"Failed to fetch URL: HTTP {exc.code}") from exc
        except URLError as exc:
            raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {exc.reason}") from exc

        text = body.decode(charset, errors="replace")
        if content_type == "text/plain":
            compact = text.strip()
            if not compact:
                raise HTTPException(status_code=400, detail="The URL returned an empty text document.")
            return UrlCaptureResult(text=f"Captured URL: {url}\n\n{compact[:12000]}", provider=self.name)

        extracted = extract_html_text(text)
        if not extracted:
            raise HTTPException(status_code=400, detail="No readable text content could be extracted from the URL.")
        return UrlCaptureResult(text=f"Captured URL: {url}\n\n{extracted[:12000]}", provider=self.name)
