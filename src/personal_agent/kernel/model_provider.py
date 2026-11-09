"""Provider identity and the shared contract for SDK parameter policies."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Annotated, Any, Literal, Mapping, Protocol
from urllib.parse import urlparse

from pydantic import StringConstraints


# Registered providers can extend configuration without changing a closed enum.
ModelProvider = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*$")]

_OFFICIAL_PROVIDERS: dict[str, str] = {
    "api.minimax.cn": "minimax",
    "api.minimax.io": "minimax",
    "api.minimaxi.com": "minimax",
    "api.xiaomimimo.com": "mimo",
    "token-plan-cn.xiaomimimo.com": "mimo",
    "api.deepseek.com": "deepseek",
}


class ModelProviderConfigurationError(ValueError):
    """The configured endpoint cannot satisfy the requested wire contract."""


def resolve_model_provider(base_url: str | None, provider: ModelProvider | None = None) -> ModelProvider:
    known = _OFFICIAL_PROVIDERS.get(urlparse(base_url or "").hostname or "")
    if provider is not None and (not isinstance(provider, str) or re.fullmatch(r"[a-z][a-z0-9_-]*", provider) is None):
        raise ModelProviderConfigurationError(f"invalid model provider identifier: {provider!r}")
    if provider is not None and known is not None and provider != known:
        raise ModelProviderConfigurationError(f"model provider {provider!r} conflicts with endpoint provider {known!r}")
    return provider or known or "openai_compatible"


@dataclass(frozen=True, slots=True)
class ChatModelCapabilities:
    """Wire capabilities, independent of SDK lifecycle and product budgets."""

    output_token_field: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    omitted_sampling_fields: tuple[Literal["temperature", "top_p"], ...] = ()


class ModelProviderPolicy(Protocol):
    def prepare_chat_parameters(
        self, parameters: Mapping[str, Any], *, defaults: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Project an external SDK envelope without mutating the input."""
        ...
