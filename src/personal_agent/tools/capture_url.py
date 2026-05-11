from __future__ import annotations

import logging
from typing import Any

from ..capture import CaptureService
from .base import BaseTool, ToolResult, ToolSpec

logger = logging.getLogger(__name__)


class CaptureUrlTool(BaseTool):
    def __init__(self, capture_service: CaptureService) -> None:
        self._capture_service = capture_service

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="capture_url",
            description="抓取指定网页的正文内容，返回提取后的纯文本。",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要抓取的网页 URL"},
                },
                "required": ["url"],
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url")
        if not url or not isinstance(url, str):
            return ToolResult(ok=False, error="缺少有效的 url 参数。")
        try:
            text = self._capture_service.capture_text_from_url(url)
            return ToolResult(ok=True, data={"url": url, "text": text})
        except Exception as exc:
            logger.exception("CaptureUrlTool failed for url=%s", url)
            return ToolResult(ok=False, error=str(exc)[:500])
