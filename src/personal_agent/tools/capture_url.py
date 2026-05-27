from __future__ import annotations

import logging

from langchain_core.tools import BaseTool, tool

from ..capture import CaptureService
from .base import tool_failure, tool_response, tool_success

logger = logging.getLogger(__name__)


def build_capture_url_tool(capture_service: CaptureService) -> BaseTool:
    @tool(
        "capture_url",
        description="抓取指定网页的正文内容，返回提取后的纯文本。",
        response_format="content_and_artifact",
        extras={"risk_level": "low", "accesses_external": True},
    )
    def capture_url(url: str):
        try:
            return tool_response(tool_success({
                "url": url,
                "text": capture_service.capture_text_from_url(url),
            }))
        except Exception as exc:
            logger.exception("capture_url failed for url=%s", url)
            return tool_response(tool_failure(str(exc)[:500]))

    return capture_url
