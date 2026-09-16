"""网页执行结果保存原始提取正文，来源身份由外层契约拥有。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.capture.models import UrlCaptureResult
from personal_agent.kernel.models import WebSearchResult


MAX_URL_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_SOURCE_PAYLOAD_BYTES = 16 * 1024 * 1024
WEB_SOURCE_FORMAT = "web-source-text-v2"


class WebSearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    results: tuple[WebSearchResult, ...]


class WebReadOutput(BaseModel):
    """一次指定来源抓取的成功结果；失败由 ToolArtifact 表达。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["web-source-text-v2"] = WEB_SOURCE_FORMAT
    source_url: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    source_text: str


def source_body_text(source: UrlCaptureResult, *, max_bytes: int) -> str:
    """Store the captured body verbatim; source metadata stays in WebReadOutput."""
    if len(source.text.encode("utf-8")) > max_bytes:
        raise ValueError("来源正文超过单次容量，未交付不完整正文。")
    return source.text

