from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.review import ReviewDigestUseCase
from personal_agent.tools.base import governance_extras, tool_response, tool_success


class ReviewDigestArgs(BaseModel):
    user_id: str = Field(default="default", description="知识归属用户 ID。")


def build_review_digest_tool(use_case: ReviewDigestUseCase) -> BaseTool:
    @tool(
        "review_digest",
        description="立即生成当前用户的知识简报，不修改订阅或触发投递。",
        args_schema=ReviewDigestArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            risk_level="low",
            side_effects=("read_longterm",),
            permission_scope="memory:read",
        ),
    )
    def review_digest(user_id: str = "default"):
        digest = use_case.generate(user_id)
        return tool_response(tool_success({
            "text": use_case.formatter.to_text(digest),
            "recent_count": len(digest.recent_notes),
            "due_count": len(digest.due_cards),
            "section_count": len(digest.sections),
        }))

    return review_digest
