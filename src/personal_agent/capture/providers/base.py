from __future__ import annotations

from ..models import UploadCaptureRequest, UrlCaptureResult


class UploadCaptureProvider:
    def capture(self, request: UploadCaptureRequest) -> str:
        raise NotImplementedError


class UrlCaptureProvider:
    name = "base"

    def can_handle(self, url: str) -> bool:
        raise NotImplementedError

    def capture(self, url: str) -> UrlCaptureResult:
        raise NotImplementedError
