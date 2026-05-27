from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from ..capture import CaptureService
from .base import tool_failure, tool_response, tool_success

logger = logging.getLogger(__name__)


def build_capture_upload_tool(capture_service: CaptureService, uploads_dir: Path | str | None = None) -> BaseTool:
    del uploads_dir

    @tool(
        "capture_upload",
        description="解析上传的文件（支持 PDF、文本文件），返回提取后的正文内容。",
        response_format="content_and_artifact",
        extras={"risk_level": "low", "writes_longterm": True},
    )
    def capture_upload(file_path: str, filename: str, content_type: str | None = None):
        path = Path(file_path)
        if not path.exists():
            return tool_response(tool_failure(f"文件不存在：{file_path}"))
        try:
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
        except Exception as exc:
            logger.exception("capture_upload failed for file=%s", filename)
            return tool_response(tool_failure(str(exc)[:500]))

    return capture_upload
