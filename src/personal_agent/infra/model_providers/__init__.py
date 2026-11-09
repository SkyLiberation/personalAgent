"""Explicit provider assembly; SDK consumers receive the selected policy."""

from collections.abc import Callable, Mapping
from types import MappingProxyType

from personal_agent.kernel.model_provider import (
    ModelProvider,
    ModelProviderConfigurationError,
    ModelProviderPolicy,
    resolve_model_provider,
)

from .deepseek import DeepSeekPolicy
from .mimo import MiMoPolicy
from .minimax import MiniMaxPolicy
from .openai_compatible import OpenAICompatiblePolicy


ProviderFactories = Mapping[str, Callable[[], ModelProviderPolicy]]
DEFAULT_PROVIDER_FACTORIES: ProviderFactories = MappingProxyType({
    "openai_compatible": OpenAICompatiblePolicy,
    "minimax": MiniMaxPolicy,
    "mimo": MiMoPolicy,
    "deepseek": DeepSeekPolicy,
})


def build_provider_policy(
    *, base_url: str | None, provider: ModelProvider | None = None,
    factories: ProviderFactories = DEFAULT_PROVIDER_FACTORIES,
) -> ModelProviderPolicy:
    name = resolve_model_provider(base_url, provider)
    try:
        factory = factories[name]
    except KeyError as exc:
        raise ModelProviderConfigurationError(f"unregistered model provider: {name!r}") from exc
    return factory()
