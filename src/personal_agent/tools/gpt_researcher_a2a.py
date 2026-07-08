from __future__ import annotations

from typing import Protocol

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.infra.a2a import A2AResearchResponse, GPTResearcherA2AClient
from personal_agent.kernel.config_models import GPTResearcherA2AConfig
from personal_agent.tools.base import governance_extras, tool_response, tool_success


class GPTResearcherA2AProtocol(Protocol):
    def research(
        self,
        *,
        topic: str,
        report_type: str | None = None,
        report_source: str | None = None,
        tone: str | None = None,
        max_search_results: int | None = None,
        blocking: bool = True,
    ) -> A2AResearchResponse: ...


class GPTResearcherA2AArgs(BaseModel):
    topic: str = Field(..., min_length=1, description="要委托 GPT Researcher 调研的问题或主题。")
    report_type: str | None = Field(default=None, description="GPT Researcher report_type。")
    report_source: str | None = Field(default=None, description="GPT Researcher report_source。")
    tone: str | None = Field(default=None, description="GPT Researcher 报告语气。")
    max_search_results: int | None = Field(default=None, ge=1, le=50, description="单次调研最大搜索结果数。")
    user_id: str = "default"
    run_id: str | None = None


def build_gpt_researcher_a2a_tool(
    config: GPTResearcherA2AConfig,
    client: GPTResearcherA2AProtocol | None = None,
) -> BaseTool:
    research_client = client or GPTResearcherA2AClient(config)

    @tool(
        "gpt_researcher.a2a_research",
        description=(
            "通过本地部署的 GPT Researcher A2A JSON-RPC 后端执行深度网页研究，"
            "返回带 artifact 和报告元数据的 Markdown 研究报告。"
        ),
        args_schema=GPTResearcherA2AArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent",
            risk_level="medium",
            side_effects=("external_network",),
            permission_scope="a2a:gpt_researcher:research",
            timeout_seconds=config.timeout_seconds,
            max_retries=1,
            retry_backoff_seconds=1.0,
            rate_limit_per_minute=5,
            allowed_domains=("localhost", "127.0.0.1"),
        ),
    )
    def gpt_researcher_a2a_research(
        topic: str,
        report_type: str | None = None,
        report_source: str | None = None,
        tone: str | None = None,
        max_search_results: int | None = None,
        user_id: str = "default",
        run_id: str | None = None,
    ):
        response = research_client.research(
            topic=topic,
            report_type=report_type,
            report_source=report_source,
            tone=tone,
            max_search_results=max_search_results,
            blocking=True,
        )
        data = {
            "provider": "gpt_researcher_a2a",
            "task_id": response.task_id,
            "context_id": response.context_id,
            "state": response.state,
            "report": response.report,
            "artifacts": response.artifacts,
            "metadata": response.metadata,
            "user_id": user_id,
            "run_id": run_id,
        }
        return tool_response(tool_success(data))

    return gpt_researcher_a2a_research


__all__ = ["GPTResearcherA2AArgs", "GPTResearcherA2AProtocol", "build_gpt_researcher_a2a_tool"]
