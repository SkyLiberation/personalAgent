from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from ..insight import KnowledgeGapUseCase
from .base import governance_extras, tool_response, tool_success


class InspectKnowledgeGapsArgs(BaseModel):
    user_id: str = Field(default="default", description="知识归属用户 ID。")


def build_inspect_knowledge_gaps_tool(use_case: KnowledgeGapUseCase) -> BaseTool:
    @tool(
        "inspect_knowledge_gaps",
        description="分析当前用户知识库中的孤岛、薄弱连接和潜在冲突。",
        args_schema=InspectKnowledgeGapsArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            risk_level="low",
            side_effects=("read_longterm",),
            permission_scope="memory:read",
        ),
    )
    def inspect_knowledge_gaps(user_id: str = "default"):
        report = use_case.inspect(user_id)
        return tool_response(tool_success({
            "text": report.text,
            "gaps": report.gaps,
            "gap_count": len(report.gaps),
        }))

    return inspect_knowledge_gaps
