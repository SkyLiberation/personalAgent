from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from personal_agent.kernel.config import Settings
from personal_agent.kernel.models import WebSearchResult

logger = logging.getLogger(__name__)


class WebSearchProvider(ABC):
    name = "web_search"

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[WebSearchResult]:
        raise NotImplementedError


class TavilyWebSearchProvider(WebSearchProvider):
    """Call Tavily /search to find web pages matching a query.

    Only active when the configured web search API key is present. A valid empty
    result is distinct from a rejected or unavailable provider call.
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
            detail = exc.read()[:500]
            logger.error(
                "Tavily search HTTP %s for query=%s: %s",
                exc.code,
                query[:80],
                detail,
            )
            message = f"Tavily search rejected the request with HTTP {exc.code}: {detail!r}"
            if exc.code in {401, 403}:
                raise PermissionError(message) from exc
            if exc.code == 429 or exc.code >= 500:
                raise ConnectionError(message) from exc
            raise ValueError(message) from exc
        except URLError as exc:
            logger.error("Tavily search URL error for query=%s: %s", query[:80], exc)
            raise ConnectionError(f"Tavily search is unavailable: {exc}") from exc
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("Tavily search invalid JSON for query=%s: %s", query[:80], exc)
            raise RuntimeError("Tavily search returned an invalid response") from exc

        results_raw = data.get("results", [])
        if not isinstance(results_raw, list):
            raise RuntimeError("Tavily search response has no results list")

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


class SerpApiWebSearchProvider(WebSearchProvider):
    """Call SerpAPI Google Search through the generic web-search credential."""

    name = "serpapi"

    def __init__(self, settings: Settings, _logger: logging.Logger | None = None) -> None:
        self._settings = settings
        if _logger is not None:
            self.logger = _logger

    def search(self, query: str, limit: int = 5) -> list[WebSearchResult]:
        api_key = self._settings.web_search.api_key
        if not api_key:
            raise PermissionError("SerpAPI search requires an API key")

        base_url = (self._settings.web_search.base_url or "https://serpapi.com").rstrip("/")
        endpoint = base_url if base_url.endswith("/search.json") else f"{base_url}/search.json"
        query_string = urlencode({
            "engine": "google",
            "hl": "en",
            "q": query,
            "num": min(limit, 10),
            "api_key": api_key,
        })
        request = Request(
            f"{endpoint}?{query_string}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        timeout_seconds = max(5, self._settings.web_search.timeout_ms / 1000)

        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read()[:500]
            logger.error(
                "SerpAPI search HTTP %s for query=%s",
                exc.code,
                query[:80],
            )
            message = f"SerpAPI search rejected the request with HTTP {exc.code}: {detail!r}"
            if exc.code in {401, 403}:
                raise PermissionError(message) from exc
            if exc.code in {402, 429} or exc.code >= 500:
                raise ConnectionError(message) from exc
            raise ValueError(message) from exc
        except URLError as exc:
            logger.error("SerpAPI search URL error for query=%s: %s", query[:80], exc.reason)
            raise ConnectionError("SerpAPI search is unavailable") from exc
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("SerpAPI search invalid JSON for query=%s: %s", query[:80], exc)
            raise RuntimeError("SerpAPI search returned invalid JSON") from exc

        if not isinstance(data, dict):
            raise RuntimeError("SerpAPI search returned an invalid response")
        provider_error = data.get("error")
        if provider_error:
            if (
                isinstance(provider_error, str)
                and "hasn't returned any results for this query"
                in provider_error.lower()
            ):
                return []
            raise RuntimeError(f"SerpAPI search failed: {provider_error}")
        results_raw = data.get("organic_results")
        if not isinstance(results_raw, list):
            raise RuntimeError("SerpAPI search response has no organic_results list")

        return [
            WebSearchResult(
                title=str(item.get("title", "")),
                url=str(item.get("link", "")),
                snippet=str(item.get("snippet", "")),
                source=self.name,
                published_at=item.get("date"),
            )
            for item in results_raw[:min(limit, 10)]
            if isinstance(item, dict)
        ]


def build_web_search_provider(settings: Settings) -> WebSearchProvider:
    provider = settings.web_search.provider.strip().lower()
    providers = {
        SerpApiWebSearchProvider.name: SerpApiWebSearchProvider,
        TavilyWebSearchProvider.name: TavilyWebSearchProvider,
    }
    if provider in providers:
        return providers[provider](settings)
    raise ValueError(f"Unsupported web search provider: {settings.web_search.provider}")
