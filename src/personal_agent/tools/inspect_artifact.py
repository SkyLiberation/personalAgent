from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.application.artifacts import ArtifactService
from personal_agent.tools.base import ToolError, governance_extras, tool_response, tool_success


class InspectArtifactArgs(BaseModel):
    file_path: str = Field(default="", description="服务端 artifact 文件路径，由入口上传链路提供。")
    filename: str = Field(default="", description="用户上传时的原始文件名。")
    content_type: str | None = Field(default=None, description="上传文件 MIME type；未知时可为空。")
    source_type: str | None = Field(default=None, description="artifact 类型：pdf/image/audio/note/file。")
    question: str = Field(default="", description="用户围绕该 artifact 的问题或总结要求。")


def build_inspect_artifact_tool(artifact_service: ArtifactService) -> BaseTool:
    @tool(
        "inspect_artifact",
        description=(
            "理解当前用户上传的 artifact，返回可供回答或入库的文本化上下文。"
            "它不会把内容写入长期知识库；保存必须由后续 capture_text 显式完成。"
        ),
        args_schema=InspectArtifactArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            risk_level="low",
            side_effects=(),
            permission_scope="artifact:read",
            timeout_seconds=60.0,
            max_retries=0,
            rate_limit_per_minute=20,
        ),
    )
    def inspect_artifact(
        file_path: str = "",
        filename: str = "",
        content_type: str | None = None,
        source_type: str | None = None,
        question: str = "",
    ):
        if not file_path:
            raise ToolError("缺少 artifact 文件路径。", kind="invalid_param")
        if not filename:
            raise ToolError("缺少 artifact 文件名。", kind="invalid_param")
        result = artifact_service.inspect_upload(
            file_path=file_path,
            filename=filename,
            content_type=content_type,
            source_type=source_type,
            question=question,
        )
        return tool_response(tool_success(result))

    return inspect_artifact
