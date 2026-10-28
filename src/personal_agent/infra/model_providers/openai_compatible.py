"""Shared OpenAI wire encoding; provider-specific behavior is injected."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict

from personal_agent.kernel.model_provider import ChatModelCapabilities, ModelProviderConfigurationError


_MANAGED_FIELDS = frozenset({
    "model", "messages", "tools", "tool_choice", "response_format", "stream",
    "stream_options", "max_tokens", "max_completion_tokens", "temperature", "top_p",
})
_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"})
ThinkingMode = Literal["enabled", "disabled", "adaptive"]


class _Thinking(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: ThinkingMode


@dataclass(slots=True)
class ChatParameters:
    """One request-local view of an external SDK envelope."""

    model: str
    sdk: dict[str, Any]
    extra_body: dict[str, Any]
    reasoning_effort: str | None

    @classmethod
    def parse(cls, parameters: Mapping[str, Any], defaults: Mapping[str, Any] | None) -> ChatParameters:
        kwargs = dict(parameters)
        model = kwargs.get("model")
        if not isinstance(model, str) or not model:
            raise ModelProviderConfigurationError("model request must specify its actual model")
        extra = {**(defaults or {}), **(kwargs.pop("extra_body", None) or {})}
        conflicts = _MANAGED_FIELDS.intersection(extra)
        if conflicts:
            raise ModelProviderConfigurationError(f"extra_body overrides managed model fields: {', '.join(sorted(conflicts))}")
        effort = kwargs.pop("reasoning_effort", None)
        configured_effort = extra.pop("reasoning_effort", None)
        if effort is None:
            effort = configured_effort
        if effort is not None and (not isinstance(effort, str) or effort not in _EFFORTS):
            raise ModelProviderConfigurationError("unsupported reasoning_effort value")
        return cls(model, kwargs, extra, effort)

    def thinking_mode(self) -> ThinkingMode | None:
        return _Thinking.model_validate(self.extra_body["thinking"]).type if "thinking" in self.extra_body else None

    def encode(self, capabilities: ChatModelCapabilities) -> dict[str, Any]:
        limits = [self.sdk.pop(name) for name in ("max_tokens", "max_completion_tokens") if name in self.sdk]
        if len(limits) > 1:
            raise ModelProviderConfigurationError("model request specifies two output token limits")
        if limits and limits[0] is not None:
            self.sdk[capabilities.output_token_field] = limits[0]
        for field in capabilities.omitted_sampling_fields:
            self.sdk.pop(field, None)
        return self.sdk


class OpenAICompatiblePolicy:
    """Common encoder, also usable with a fixed capability profile."""

    def __init__(self, capabilities: ChatModelCapabilities | None = None) -> None:
        self._capabilities = capabilities

    def configure(self, request: ChatParameters) -> ChatModelCapabilities:
        if self._capabilities is not None:
            return self._capabilities
        reasoning = request.model.lower().startswith(("gpt-5", "o1", "o3", "mimo", "minimax-"))
        return ChatModelCapabilities("max_completion_tokens", ("temperature", "top_p")) if reasoning else ChatModelCapabilities()

    def prepare_tools(self, parameters: dict[str, Any], request: ChatParameters) -> None:
        """Providers override this only when tool transport needs adaptation."""

    def prepare_chat_parameters(
        self, parameters: Mapping[str, Any], *, defaults: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = ChatParameters.parse(parameters, defaults)
        kwargs = request.encode(self.configure(request))
        self.prepare_tools(kwargs, request)
        if request.reasoning_effort is not None:
            kwargs["reasoning_effort"] = request.reasoning_effort
        if request.extra_body:
            kwargs["extra_body"] = request.extra_body
        return kwargs
