from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.application.artifacts import ArtifactService
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
from personal_agent.tools.base import governance_extras, tool_response, tool_success


class InspectArtifactArgs(BaseModel):
    resource_ref: ResourceRef
    user_id: str = Field(min_length=1)
    question: str = Field(default="", description="用户围绕该 artifact 的问题或总结要求。")


def build_inspect_artifact_tool(artifact_service: ArtifactService) -> BaseTool:
    @tool(
        "inspect_artifact",
        description="按 application-owned ResourceRef 读取上传 artifact 并返回 typed EvidenceRef；不会写入长期知识库。",
        args_schema=InspectArtifactArgs,
        response_format="content_and_artifact",
        extras=governance_extras(exposure="public_agent", risk_level="low", side_effects=("read_local",), permission_scope="artifact:read", timeout_seconds=60.0, max_retries=0, rate_limit_per_minute=20),
    )
    def inspect_artifact(resource_ref: ResourceRef, user_id: str, question: str = ""):
        result = artifact_service.inspect_upload(
            resource_ref=resource_ref,
            principal=AuthenticatedPrincipal(
                tenant_id=resource_ref.owner.tenant_id,
                user_id=user_id,
            ),
            owner=resource_ref.owner,
            question=question,
        )
        return tool_response(tool_success(result, evidence=result["evidence_refs"]))

    return inspect_artifact
