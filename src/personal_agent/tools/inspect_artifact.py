from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from langchain_core.tools import BaseTool, tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.artifacts import ArtifactService
from personal_agent.application.artifacts.models import resolve_artifact_ref
from personal_agent.tools.base import (
    governance_extras,
    require_gateway_context,
    tool_response,
    tool_success,
)


class InspectArtifactArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_id: str = Field(min_length=1, description="当前材料或成功结果提供的Artifact resource_id。")
    question: str = Field(
        default="", description="用户围绕该 artifact 的问题或总结要求。"
    )


def build_inspect_artifact_tool(artifact_service: ArtifactService, *, prompts: PromptCatalog = DEFAULT_PROMPTS) -> BaseTool:
    @tool(
        "inspect_artifact",
        description="读取当前可读文件，按问题提取内容并返回来源引用；不会写入长期知识库。",
        args_schema=InspectArtifactArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent",
            risk_level="low",
            side_effects=("read_local",),
            permission_scope="artifact:read",
            timeout_seconds=60.0,
            max_retries=0,
            rate_limit_per_minute=20,
        ),
    )
    def inspect_artifact(
        resource_id: str, config: RunnableConfig, question: str = ""
    ):
        context = require_gateway_context(config, prompts=prompts)
        resource_ref = resolve_artifact_ref(
            resource_id, context.allowed_resource_refs,
            principal=context.execution_scope.principal, prompts=prompts,
        )
        result = artifact_service.inspect_upload(
            resource_ref=resource_ref,
            principal=context.execution_scope.principal,
            owner=context.execution_scope.principal,
            question=question,
        )
        return tool_response(tool_success(result, evidence=result["evidence_refs"]))

    return inspect_artifact
