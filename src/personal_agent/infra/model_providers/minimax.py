"""MiniMax model-specific thinking and sampling support."""

from personal_agent.kernel.model_provider import ChatModelCapabilities, ModelProviderConfigurationError

from .openai_compatible import ChatParameters, OpenAICompatiblePolicy


class MiniMaxPolicy(OpenAICompatiblePolicy):
    def configure(self, request: ChatParameters) -> ChatModelCapabilities:
        thinking = request.thinking_mode()
        if thinking == "enabled":
            raise ModelProviderConfigurationError("MiniMax thinking.type must be adaptive or disabled")
        adjustable = request.model.lower().startswith("minimax-m3.1")
        if thinking == "disabled" and (adjustable or not request.model.lower().startswith("minimax-m3")):
            raise ModelProviderConfigurationError(f"{request.model} does not support disabling thinking")
        effort = request.reasoning_effort
        if effort is not None and (not adjustable or effort not in {"low", "medium", "high", "xhigh", "max"}):
            raise ModelProviderConfigurationError(f"{request.model} does not support reasoning_effort={effort!r}")
        return ChatModelCapabilities("max_completion_tokens", ("temperature", "top_p"))
