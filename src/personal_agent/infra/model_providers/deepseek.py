"""DeepSeek thinking/effort interaction and supported sampling parameters."""

from typing import Any

from personal_agent.kernel.model_provider import ChatModelCapabilities, ModelProviderConfigurationError

from .openai_compatible import ChatParameters, OpenAICompatiblePolicy, ThinkingMode


class DeepSeekPolicy(OpenAICompatiblePolicy):
    @staticmethod
    def _thinking(request: ChatParameters) -> ThinkingMode | None:
        thinking = request.thinking_mode()
        if thinking == "adaptive":
            raise ModelProviderConfigurationError("deepseek thinking.type must be enabled or disabled")
        effort = request.reasoning_effort
        if effort is not None:
            if (thinking == "disabled" and effort != "none") or (thinking == "enabled" and effort == "none"):
                raise ModelProviderConfigurationError("DeepSeek thinking and reasoning_effort specify conflicting modes")
            if effort == "none":
                thinking = "disabled"
        return thinking

    def configure(self, request: ChatParameters) -> ChatModelCapabilities:
        # top_p is supported in thinking mode; only temperature is omitted.
        return ChatModelCapabilities("max_tokens", () if self._thinking(request) == "disabled" else ("temperature",))

    def prepare_tools(self, parameters: dict[str, Any], request: ChatParameters) -> None:
        if self._thinking(request) != "disabled" and parameters.get("tool_choice") == "required":
            parameters["tool_choice"] = "auto"
