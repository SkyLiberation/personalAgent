from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class UploadCaptureRequest:
    filename: str
    content_type: str | None
    file_bytes: bytes
    source_type: str


@dataclass(slots=True)
class UrlCaptureResult:
    url: str
    text: str
    provider: str
