from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..capture import CaptureService
from .base import BaseTool, ToolResult, ToolSpec

logger = logging.getLogger(__name__)


class CaptureUploadTool(BaseTool):
    def __init__(self, capture_service: CaptureService, uploads_dir: Path | str | None = None) -> None:
        self._capture_service = capture_service
        self._uploads_dir = Path(uploads_dir) if uploads_dir else Path("./data/uploads")

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="capture_upload",
            description="解析上传的文件（支持 PDF、文本文件），返回提取后的正文内容。",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "上传文件的本地路径"},
                    "filename": {"type": "string", "description": "原始文件名"},
                    "content_type": {"type": "string", "description": "MIME 类型"},
                },
                "required": ["file_path", "filename"],
            },
            risk_level="low",
            writes_longterm=True,
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        file_path = kwargs.get("file_path")
        filename = kwargs.get("filename")
        content_type = kwargs.get("content_type")
        if not file_path or not filename:
            return ToolResult(ok=False, error="缺少有效的 file_path 或 filename 参数。")

        path = Path(file_path)
        if not path.exists():
            return ToolResult(ok=False, error=f"文件不存在：{file_path}")

        try:
            file_bytes = path.read_bytes()
            source_type = self._capture_service.source_type_from_upload(filename, content_type)
            text = self._capture_service.capture_text_from_upload(
                filename=filename,
                content_type=content_type,
                file_bytes=file_bytes,
                source_type=source_type,
            )
            return ToolResult(ok=True, data={"filename": filename, "source_type": source_type, "text": text})
        except Exception as exc:
            logger.exception("CaptureUploadTool failed for file=%s", filename)
            return ToolResult(ok=False, error=str(exc)[:500])
