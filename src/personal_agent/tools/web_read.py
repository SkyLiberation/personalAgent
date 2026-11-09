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
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import create_prompt_catalog
from personal_agent.tools.base import governance_extras, tool_response, tool_success, url_allowed


class WebReadArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(
        ..., min_length=8,
        description="需要读取正文的一个 http/https URL，可来自用户、搜索结果或已知来源；不是搜索词。",
    )


def build_web_read_tool(
    settings: Settings, capture_service: CaptureService,
    *, prompts: PromptCatalog | None = None,
) -> BaseTool:
    prompts = prompts if prompts is not None else create_prompt_catalog(settings.prompt_language)
    description = prompts.get("web_read.description")
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
            raise ToolError(prompts.render('tools.web_read.domain_denied'), kind="permission")
        try:
            captured = capture_service.capture_url(url)
            if not captured.text.strip():
                raise ValueError(prompts.render('tools.web_read.no_body'))
            source_text = source_body_text(captured, max_bytes=MAX_SOURCE_PAYLOAD_BYTES, prompts=prompts)
        except HTTPException as error:
            kind = "permission" if error.status_code in {401, 403} else "unrecoverable"
            raise ToolError(prompts.render('tools.web_read.failed', detail=error.detail), kind=kind) from error
        except (TimeoutError, ConnectionError) as error:
            raise ToolError(prompts.render('tools.web_read.transient', detail=error), kind="transient") from error
        except ValueError as error:
            raise ToolError(prompts.render('tools.web_read.undelivered', detail=error)) from error
        output = WebReadOutput(
            source_url=captured.url, provider=captured.provider, source_text=source_text,
        )
        return tool_response(tool_success(output.model_dump(mode="json")))

    return web_read
