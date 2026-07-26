from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.application.artifacts import ArtifactService
from personal_agent.application.capture import CaptureService
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.tools.base import governance_extras, tool_response, tool_success


class CaptureUploadArgs(BaseModel):
    resource_ref: ResourceRef
    user_id: str = Field(min_length=1)


def build_capture_upload_tool(capture_service: CaptureService, artifact_service: ArtifactService) -> BaseTool:
    @tool(
        "capture_upload",
        description="从 application-owned ResourceRef 提取上传内容，供统一 capture ingestion 写入口消费；本步骤自身不写长期知识。",
        args_schema=CaptureUploadArgs,
        response_format="content_and_artifact",
        extras=governance_extras(exposure="workflow_activity", risk_level="low", side_effects=("read_local",), permission_scope="artifact:read", timeout_seconds=45.0, max_retries=0, rate_limit_per_minute=20),
    )
    def capture_upload(resource_ref: ResourceRef, user_id: str):
        record, file_bytes = artifact_service.read_upload(resource_ref, user_id=user_id)
        text = capture_service.capture_text_from_upload(filename=record.filename, content_type=record.content_type, file_bytes=file_bytes, source_type=record.source_type)
        return tool_response(tool_success({"resource_ref": resource_ref.model_dump(mode="json"), "filename": record.filename, "source_type": record.source_type, "text": text}))

    return capture_upload
