from __future__ import annotations

from fastapi import HTTPException
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.capture import CaptureService
from personal_agent.application.capture.web_source import (
    MAX_SOURCE_PAYLOAD_BYTES,
    WebReadOutput,
    source_body_text,
)
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.tool import ToolError
from personal_agent.kernel.prompts import get_prompt
from personal_agent.tools.base import governance_extras, tool_response, tool_success, url_allowed


class WebReadArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(
        ..., min_length=8,
        description="需要读取正文的一个 http/https URL，可来自用户、搜索结果或已知来源；不是搜索词。",
    )


def build_web_read_tool(settings: Settings, capture_service: CaptureService) -> BaseTool:
    description = get_prompt("web_read.description")
    allowed_domains = tuple(settings.web_search.allowed_domains)

    @tool(
        "web_read",
        description=description.render(version=description.version),
        args_schema=WebReadArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent", risk_level="low",
            side_effects=("external_network",), permission_scope="network:read",
            timeout_seconds=30.0, max_retries=1, retry_backoff_seconds=0.5,
            rate_limit_per_minute=20, allowed_domains=allowed_domains,
        ),
    )
    def web_read(url: str):
        if not url_allowed(url, allowed_domains):
            raise ToolError("目标域名不在允许列表中，未读取正文。", kind="permission")
        try:
            captured = capture_service.capture_url(url)
            if not captured.text.strip():
                raise ValueError("服务提供方未返回可读正文。")
            source_text = source_body_text(captured, max_bytes=MAX_SOURCE_PAYLOAD_BYTES)
        except HTTPException as error:
            kind = "permission" if error.status_code in {401, 403} else "unrecoverable"
            raise ToolError(f"网页读取失败：{error.detail}", kind=kind) from error
        except (TimeoutError, ConnectionError) as error:
            raise ToolError(f"网页读取暂时失败：{error}", kind="transient") from error
        except ValueError as error:
            raise ToolError(f"网页读取未交付正文：{error}") from error
        output = WebReadOutput(
            source_url=captured.url, provider=captured.provider, source_text=source_text,
        )
        return tool_response(tool_success(output.model_dump(mode="json")))

    return web_read
