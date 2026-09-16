from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.capture.providers.web_search import WebSearchProvider
from personal_agent.application.capture.web_source import WebSearchOutput
from personal_agent.kernel.config import Settings
from personal_agent.kernel.evidence import EvidenceItem
from personal_agent.kernel.prompts import get_prompt
from personal_agent.tools.base import governance_extras, tool_response, tool_success


class WebSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ..., min_length=1, max_length=400,
        description="要搜索的公网信息问题或关键词，最多 400 个字符。",
    )
    limit: int = Field(default=5, ge=1, le=10, description="返回搜索结果数量，范围 1-10。")


def build_web_search_tool(settings: Settings, provider: WebSearchProvider) -> BaseTool:
    description = get_prompt("web_search.description")

    @tool(
        "web_search",
        description=description.render(version=description.version),
        args_schema=WebSearchArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent", risk_level="low",
            side_effects=("external_network",), permission_scope="network:read",
            timeout_seconds=60.0, max_retries=1, retry_backoff_seconds=0.5,
            rate_limit_per_minute=30,
            allowed_domains=tuple(settings.web_search.allowed_domains),
        ),
    )
    def web_search(query: str, limit: int = 5):
        results = provider.search(query, limit=limit)
        evidence = [
            EvidenceItem(
                source_type="web", source_id=result.url, title=result.title,
                snippet=result.snippet, url=result.url,
                metadata={"source": result.source, "published_at": result.published_at},
            )
            for result in results if result.url
        ]
        output = WebSearchOutput(results=tuple(results))
        return tool_response(tool_success(output.model_dump(mode="json"), evidence))

    return web_search
