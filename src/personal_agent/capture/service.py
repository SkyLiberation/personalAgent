from __future__ import annotations

import logging

from .models import UploadCaptureRequest
from .providers import (
    BuiltinUrlCaptureProvider,
    DefaultUploadCaptureProvider,
    FirecrawlUrlCaptureProvider,
    UploadCaptureProvider,
    UrlCaptureProvider,
)
from .utils import normalize_upload_filename, source_type_from_upload, validate_capture_url
from ..core.config import Settings


class CaptureService:
    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger | None = None,
        upload_provider: UploadCaptureProvider | None = None,
        url_providers: list[UrlCaptureProvider] | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        self.upload_provider = upload_provider or DefaultUploadCaptureProvider(self.logger)
        self.url_providers = url_providers or self._build_default_url_providers()

    def register_url_provider(self, provider: UrlCaptureProvider, prepend: bool = False) -> None:
        if prepend:
            self.url_providers.insert(0, provider)
            return
        self.url_providers.append(provider)

    def set_upload_provider(self, provider: UploadCaptureProvider) -> None:
        self.upload_provider = provider

    def normalize_upload_filename(self, filename: str) -> str:
        return normalize_upload_filename(filename)

    def source_type_from_upload(self, filename: str, content_type: str | None) -> str:
        return source_type_from_upload(filename, content_type)

    def capture_text_from_upload(
        self,
        filename: str,
        content_type: str | None,
        file_bytes: bytes,
        source_type: str,
    ) -> str:
        return self.upload_provider.capture(
            UploadCaptureRequest(
                filename=filename,
                content_type=content_type,
                file_bytes=file_bytes,
                source_type=source_type,
            )
        )

    def capture_text_from_url(self, raw_url: str) -> str:
        url = validate_capture_url(raw_url)
        for provider in self.url_providers:
            if not provider.can_handle(url):
                continue
            result = provider.capture(url)
            self.logger.info("URL capture completed provider=%s url=%s", result.provider, url)
            return result.text
        raise RuntimeError("No URL capture provider is available.")

    def _build_default_url_providers(self) -> list[UrlCaptureProvider]:
        return [
            FirecrawlUrlCaptureProvider(self.settings, self.logger),
            BuiltinUrlCaptureProvider(),
        ]
