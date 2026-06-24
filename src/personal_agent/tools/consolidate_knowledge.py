from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.knowledge import KnowledgeConsolidationUseCase
from personal_agent.tools.base import governance_extras, tool_failure, tool_response, tool_success


class ConsolidateKnowledgeArgs(BaseModel):
    topic: str = Field(..., min_length=1, description="需要整理和合并的知识主题。")
    user_id: str = Field(default="default", description="知识归属用户 ID。")


def build_consolidate_knowledge_tool(
    use_case: KnowledgeConsolidationUseCase,
) -> BaseTool:
    @tool(
        "consolidate_knowledge",
        description="按主题选择相关笔记，生成综述并以 supersede 关系替代来源笔记。",
        args_schema=ConsolidateKnowledgeArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            risk_level="low",
            side_effects=("write_longterm",),
            permission_scope="memory:write",
            timeout_seconds=120.0,
            max_retries=0,
            rate_limit_per_minute=10,
        ),
    )
    def consolidate_knowledge(topic: str, user_id: str = "default"):
        result = use_case.execute(topic=topic, user_id=user_id)
        if not result.ok:
            return tool_response(tool_failure(result.error or "主题整理失败。"))
        return tool_response(tool_success(result.model_dump(mode="json")))

    return consolidate_knowledge
