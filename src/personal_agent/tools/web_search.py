from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.application.capture.providers.web_search import WebSearchProvider
from personal_agent.kernel.config import Settings
from personal_agent.kernel.evidence import EvidenceItem
from personal_agent.tools.base import governance_extras, tool_response, tool_success, url_allowed

if TYPE_CHECKING:
    from personal_agent.application.capture import CaptureService

logger = logging.getLogger(__name__)


class WebSearchArgs(BaseModel):
    query: str = Field(..., min_length=1, description="要搜索的公网信息问题或关键词。")
    limit: int = Field(default=5, ge=1, le=10, description="返回搜索结果数量，范围 1-10。")
    scrape: bool = Field(
        default=False,
        description="是否抓取前两个结果正文摘要；只有摘要不足以回答时才设为 true。",
    )


def build_web_search_tool(
    settings: Settings,
    provider: WebSearchProvider,
    capture_service: "CaptureService | None" = None,
) -> BaseTool:
    allowed_domains = tuple(settings.web_search.allowed_domains)

    @tool(
        "web_search",
        description=(
            "在公网搜索最新或个人知识库无法覆盖的信息，返回标题、URL、摘要和 evidence。"
            "会访问外部网络；优先使用 graph_search 查询个人知识，只有本地证据不足或问题需要最新公开信息时调用。"
            "limit 必须在 1-10；scrape=true 会额外抓取正文摘要，成本更高，仅在搜索摘要不足时使用。"
        ),
        args_schema=WebSearchArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent",
            risk_level="low",
            side_effects=("external_network",),
            permission_scope="network:read",
            timeout_seconds=20.0,
            max_retries=1,
            retry_backoff_seconds=0.5,
            rate_limit_per_minute=30,
            allowed_domains=allowed_domains,
        ),
    )
    def web_search(query: str, limit: int = 5, scrape: bool = False):
        results = provider.search(query, limit=limit)
        if scrape and results and capture_service is not None:
            for result in results[:2]:
                if not result.url:
                    continue
                if not url_allowed(result.url, allowed_domains):
                    result.snippet = (
                        (result.snippet or "")
                        + "\n---\n正文摘要: 已跳过抓取，目标域名不在允许列表中。"
                    )
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

    return web_search
