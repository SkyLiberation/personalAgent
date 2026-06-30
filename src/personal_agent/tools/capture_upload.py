from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.application.capture import CaptureService
from personal_agent.tools.base import ToolError, governance_extras, tool_response, tool_success

logger = logging.getLogger(__name__)


class CaptureUploadArgs(BaseModel):
    file_path: str = Field(..., min_length=1, description="服务端已接收的上传文件路径。")
    filename: str = Field(..., min_length=1, description="用户上传时的原始文件名，用于判断来源类型和展示。")
    content_type: str | None = Field(default=None, description="上传文件 MIME type；未知时可为空。")


def build_capture_upload_tool(capture_service: CaptureService, uploads_dir: Path | str | None = None) -> BaseTool:
    del uploads_dir

    @tool(
        "capture_upload",
        description=(
            "解析用户上传文件并提取正文，适合 capture_file 流程中处理 PDF 或文本文件。"
            "只能处理上传链路产生的文件路径；不要用它读取任意本地文件或已经入库的笔记。"
            "返回 artifact.data.filename/source_type/text，后续可进入长期知识写入流程。"
        ),
        args_schema=CaptureUploadArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            risk_level="low",
            side_effects=(),
            permission_scope="artifact:read",
            timeout_seconds=45.0,
            max_retries=0,
            rate_limit_per_minute=20,
        ),
    )
    def capture_upload(file_path: str, filename: str, content_type: str | None = None):
        path = Path(file_path)
        if not path.exists():
            raise ToolError(f"文件不存在：{file_path}", kind="invalid_param")
        source_type = capture_service.source_type_from_upload(filename, content_type)
        text = capture_service.capture_text_from_upload(
            filename=filename,
            content_type=content_type,
            file_bytes=path.read_bytes(),
            source_type=source_type,
        )
        return tool_response(tool_success({
            "filename": filename,
            "source_type": source_type,
            "text": text,
        }))

    return capture_upload
