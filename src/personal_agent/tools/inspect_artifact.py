from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.artifacts import ArtifactService
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.tools.base import (
    governance_extras,
    require_gateway_context,
    tool_response,
    tool_success,
)


class InspectArtifactArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_ref: ResourceRef
    question: str = Field(
        default="", description="用户围绕该 artifact 的问题或总结要求。"
    )


def build_inspect_artifact_tool(artifact_service: ArtifactService) -> BaseTool:
    @tool(
        "inspect_artifact",
        description="按 application-owned ResourceRef 读取上传 artifact 并返回 typed EvidenceRef；不会写入长期知识库。",
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
        resource_ref: ResourceRef, config: RunnableConfig, question: str = ""
    ):
        context = require_gateway_context(config)
        if resource_ref not in context.allowed_resource_refs:
            raise PermissionError("该资源不在本任务当前可读集合中。")
        result = artifact_service.inspect_upload(
            resource_ref=resource_ref,
            principal=context.execution_scope.principal,
            owner=context.execution_scope.principal,
            question=question,
        )
        return tool_response(tool_success(result, evidence=result["evidence_refs"]))

    return inspect_artifact
