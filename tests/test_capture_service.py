from personal_agent.application.capture import CaptureService
from personal_agent.application.capture.providers import (
    BuiltinUrlCaptureProvider,
    FirecrawlUrlCaptureProvider,
)
from personal_agent.kernel.config import Settings
from personal_agent.kernel.config_models import FirecrawlConfig


def test_capture_service_uses_one_explicit_builtin_provider() -> None:
    service = CaptureService(Settings(
        url_capture_provider="builtin",
        firecrawl=FirecrawlConfig(api_key="configured-firecrawl-key"),
    ))

    assert len(service.url_providers) == 1
    assert isinstance(service.url_providers[0], BuiltinUrlCaptureProvider)


def test_capture_service_uses_one_explicit_firecrawl_provider() -> None:
    service = CaptureService(Settings(
        url_capture_provider="firecrawl",
        firecrawl=FirecrawlConfig(api_key="configured-firecrawl-key"),
    ))

    assert len(service.url_providers) == 1
    assert isinstance(service.url_providers[0], FirecrawlUrlCaptureProvider)
