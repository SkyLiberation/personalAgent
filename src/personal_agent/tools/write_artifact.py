"""Save immutable program/config drafts through the accepted tool boundary."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from personal_agent.application.artifacts import ArtifactService
from personal_agent.application.artifacts.models import ArtifactWriteRequest
from personal_agent.application.conversation.tool_requests import WriteArtifactArgs
from personal_agent.kernel.contracts.tool_runtime import accepted_tool_request_digest
from personal_agent.kernel.prompts import get_prompt
from personal_agent.tools.base import (
    governance_extras,
    require_gateway_context,
    tool_response,
    tool_success,
)


def build_write_artifact_tool(artifact_service: ArtifactService) -> BaseTool:
    @tool(
        "write_artifact",
        description=get_prompt("artifact.write.description").template,
        args_schema=WriteArtifactArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent",
            side_effects=("write_local",),
            permission_scope="artifact:write",
            timeout_seconds=None,
            max_retries=0,
        ),
    )
    def write_artifact(request: ArtifactWriteRequest, config: RunnableConfig):
        context = require_gateway_context(config)
        arguments = WriteArtifactArgs(request=request)
        digest = accepted_tool_request_digest(
            execution_scope=context.execution_scope,
            action_id=context.tool_call_id,
            tool_name="write_artifact",
            arguments=arguments,
        )
        if context.accepted_request_digest != digest:
            raise PermissionError("保存请求没有与本次执行身份绑定的已接受记录。")
        receipt = artifact_service.write_draft(
            execution_scope=context.execution_scope,
            tool_call_id=context.tool_call_id,
            request=arguments.request,
            allowed_resource_refs=context.allowed_resource_refs,
        )
        return tool_response(tool_success(receipt.model_dump(mode="json")))

    return write_artifact
