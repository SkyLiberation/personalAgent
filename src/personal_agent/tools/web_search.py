from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from ..capture.providers.web_search import FirecrawlWebSearchProvider
from ..core.config import Settings
from ..core.evidence import EvidenceItem
from .base import BaseTool, ToolResult, ToolSpec

if TYPE_CHECKING:
    from ..capture import CaptureService

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """Search the public web, returning structured results.

    Intended as a third-tier fallback when personal graph and local
    memory both fail to cover a question.  Requires a Firecrawl API key.
    """

    def __init__(
        self,
        settings: Settings,
        provider: FirecrawlWebSearchProvider,
        capture_service: "CaptureService | None" = None,
    ) -> None:
        self._settings = settings
        self._provider = provider
        self._capture_service = capture_service

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_search",
            description="在公网互联网上搜索与问题相关的最新信息，返回网页标题、URL 和摘要。仅在个人知识库和图谱无法覆盖时使用。",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询词"},
                    "limit": {"type": "integer", "description": "返回结果数量上限，默认 5，最大 10"},
                    "scrape": {"type": "boolean", "description": "是否抓取结果页面的正文内容，默认 false"},
                },
                "required": ["query"],
            },
            risk_level="low",
            accesses_external=True,
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query")
        if not query or not isinstance(query, str):
            return ToolResult(ok=False, error="缺少有效的 query 参数。")

        if not self._settings.firecrawl_api_key:
            return ToolResult(ok=False, error="Firecrawl API key 未配置，无法执行网络搜索。")

        limit_val = kwargs.get("limit", 5)
        if not isinstance(limit_val, int) or limit_val < 1:
            limit_val = 5
        limit_val = min(limit_val, 10)

        scrape = kwargs.get("scrape", False)
        if not isinstance(scrape, bool):
            scrape = False

        try:
            results = self._provider.search(query, limit=limit_val)
            if scrape and results and self._capture_service is not None:
                for r in results[:2]:
                    url = r.url
                    if not url:
                        continue
                    try:
                        body = self._capture_service.capture_text_from_url(url)
                        r.snippet = (r.snippet or "") + f"\n---\n正文摘要: {body[:2000]}"
                    except Exception:
                        logger.exception("WebSearchTool scrape failed for url=%s", url)

            evidence = [
                EvidenceItem(
                    source_type="web",
                    source_id=r.url,
                    title=r.title,
                    snippet=r.snippet,
                    url=r.url,
                    metadata={"source": r.source, "published_at": r.published_at},
                )
                for r in results
                if r.url
            ]

            return ToolResult(ok=True, data={
                "results": [r.model_dump(mode="json") for r in results],
            }, evidence=evidence)
        except Exception as exc:
            logger.exception("WebSearchTool failed for query=%s", query[:80])
            return ToolResult(ok=False, error=str(exc)[:500])
