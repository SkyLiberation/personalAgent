from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ...core.config import Settings
from ...core.models import WebSearchResult

logger = logging.getLogger(__name__)


class FirecrawlWebSearchProvider:
    """Call Firecrawl /v1/search to find web pages matching a query.

    Only active when firecrawl_api_key is configured.  Returns an empty
    list on any error so callers can degrade gracefully.
    """

    name = "firecrawl"

    def __init__(self, settings: Settings, _logger: logging.Logger | None = None) -> None:
        self._settings = settings
        if _logger is not None:
            self.logger = _logger

    def search(self, query: str, limit: int = 5) -> list[WebSearchResult]:
        base_url = self._settings.firecrawl_base_url.rstrip("/")
        payload: dict[str, Any] = {"query": query, "limit": min(limit, 10)}
        request = Request(
            f"{base_url}/v1/search",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._settings.firecrawl_api_key}",
            },
            method="POST",
        )
        timeout_seconds = max(5, self._settings.firecrawl_timeout_ms / 1000)

        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8")
                data = json.loads(body)
        except HTTPError as exc:
            logger.error("Firecrawl search HTTP %s for query=%s: %s", exc.code, query[:80], exc.read()[:500])
            return []
        except URLError as exc:
            logger.error("Firecrawl search URL error for query=%s: %s", query[:80], exc)
            return []
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("Firecrawl search invalid JSON for query=%s: %s", query[:80], exc)
            return []

        results_raw = data.get("data", [])
        if not isinstance(results_raw, list):
            logger.warning("Firecrawl search unexpected response shape for query=%s", query[:80])
            return []

        results: list[WebSearchResult] = []
        for item in results_raw:
            if not isinstance(item, dict):
                continue
            results.append(WebSearchResult(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                snippet=str(item.get("description", item.get("snippet", ""))),
                source="firecrawl",
                published_at=item.get("published_at") or item.get("publishedAt"),
            ))
        return results
