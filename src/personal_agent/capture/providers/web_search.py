from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from personal_agent.core.config import Settings
from personal_agent.core.models import WebSearchResult

logger = logging.getLogger(__name__)


class WebSearchProvider(ABC):
    name = "web_search"

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[WebSearchResult]:
        raise NotImplementedError


class TavilyWebSearchProvider(WebSearchProvider):
    """Call Tavily /search to find web pages matching a query.

    Only active when the configured web search API key is present. Returns an empty
    list on any error so callers can degrade gracefully.
    """

    name = "tavily"

    def __init__(self, settings: Settings, _logger: logging.Logger | None = None) -> None:
        self._settings = settings
        if _logger is not None:
            self.logger = _logger

    def search(self, query: str, limit: int = 5) -> list[WebSearchResult]:
        base_url = (self._settings.web_search.base_url or "https://api.tavily.com").rstrip("/")
        payload: dict[str, Any] = {
            "query": query,
            "max_results": min(limit, 10),
            "search_depth": "basic",
            "include_answer": False,
        }
        request = Request(
            f"{base_url}/search",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._settings.web_search.api_key}",
            },
            method="POST",
        )
        timeout_seconds = max(5, self._settings.web_search.timeout_ms / 1000)

        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8")
                data = json.loads(body)
        except HTTPError as exc:
            logger.error("Tavily search HTTP %s for query=%s: %s", exc.code, query[:80], exc.read()[:500])
            return []
        except URLError as exc:
            logger.error("Tavily search URL error for query=%s: %s", query[:80], exc)
            return []
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("Tavily search invalid JSON for query=%s: %s", query[:80], exc)
            return []

        results_raw = data.get("results", [])
        if not isinstance(results_raw, list):
            logger.warning("Tavily search unexpected response shape for query=%s", query[:80])
            return []

        results: list[WebSearchResult] = []
        for item in results_raw:
            if not isinstance(item, dict):
                continue
            results.append(WebSearchResult(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                snippet=str(item.get("content", item.get("snippet", ""))),
                source="tavily",
                published_at=item.get("published_date") or item.get("publishedAt"),
            ))
        return results


def build_web_search_provider(settings: Settings) -> WebSearchProvider:
    provider = settings.web_search.provider.strip().lower()
    providers = {
        TavilyWebSearchProvider.name: TavilyWebSearchProvider,
    }
    if provider in providers:
        return providers[provider](settings)
    raise ValueError(f"Unsupported web search provider: {settings.web_search.provider}")
