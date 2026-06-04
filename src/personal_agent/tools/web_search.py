from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, tool

from ..capture.providers.web_search import FirecrawlWebSearchProvider
from ..core.config import Settings
from ..core.evidence import EvidenceItem
from .base import governance_extras, tool_failure, tool_response, tool_success

if TYPE_CHECKING:
    from ..capture import CaptureService

logger = logging.getLogger(__name__)


def build_web_search_tool(
    settings: Settings,
    provider: FirecrawlWebSearchProvider,
    capture_service: "CaptureService | None" = None,
) -> BaseTool:
    @tool(
        "web_search",
        description="在公网互联网上搜索与问题相关的最新信息，返回网页标题、URL 和摘要。会访问外部网络；仅在个人知识库和图谱无法覆盖时使用。",
        response_format="content_and_artifact",
        extras=governance_extras(
            risk_level="low",
            side_effects=("external_network",),
            permission_scope="network:read",
        ),
    )
    def web_search(query: str, limit: int = 5, scrape: bool = False):
        if not settings.firecrawl.api_key:
            return tool_response(tool_failure("Firecrawl API key 未配置，无法执行网络搜索。"))
        limit = max(1, min(limit, 10))
        try:
            results = provider.search(query, limit=limit)
            if scrape and results and capture_service is not None:
                for result in results[:2]:
                    if not result.url:
                        continue
                    try:
                        body = capture_service.capture_text_from_url(result.url)
                        result.snippet = (result.snippet or "") + f"\n---\n正文摘要: {body[:2000]}"
                    except Exception:
                        logger.exception("web_search scrape failed for url=%s", result.url)
            evidence = [
                EvidenceItem(
                    source_type="web", source_id=result.url, title=result.title,
                    snippet=result.snippet, url=result.url,
                    metadata={"source": result.source, "published_at": result.published_at},
                )
                for result in results if result.url
            ]
            return tool_response(tool_success({
                "results": [result.model_dump(mode="json") for result in results],
            }, evidence))
        except Exception as exc:
            logger.exception("web_search failed for query=%s", query[:80])
            return tool_response(tool_failure(str(exc)[:500]))

    return web_search
