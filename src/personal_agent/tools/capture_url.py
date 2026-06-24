from __future__ import annotations

import logging

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from ..capture import CaptureService
from .base import governance_extras, tool_response, tool_success

logger = logging.getLogger(__name__)


class CaptureUrlArgs(BaseModel):
    url: str = Field(
        ...,
        min_length=8,
        description="需要抓取正文的 http/https URL；不要传入本地文件路径或已经入库的笔记 ID。",
    )


def build_capture_url_tool(capture_service: CaptureService) -> BaseTool:
    @tool(
        "capture_url",
        description=(
            "抓取指定网页正文并返回纯文本，适合用户要求采集一个链接内容时使用。"
            "会访问外部网络；如果已有上传文件、本地笔记或图谱结果足够回答，不要调用。"
            "返回 artifact.data.url/text，后续需要入库时应由采集链路继续处理。"
        ),
        args_schema=CaptureUrlArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            risk_level="low",
            side_effects=("external_network",),
            permission_scope="network:read",
            timeout_seconds=30.0,
            max_retries=1,
            retry_backoff_seconds=0.5,
            rate_limit_per_minute=20,
        ),
    )
    def capture_url(url: str):
        return tool_response(tool_success({
            "url": url,
            "text": capture_service.capture_text_from_url(url),
        }))

    return capture_url
