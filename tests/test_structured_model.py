from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from personal_agent.kernel.config_models import LangSmithConfig, StructuredConfig
from personal_agent.infra.structured_model import (
    FullTracePayloadPolicy,
    ObservedStructuredModelClient,
    OpenAIModelClient,
    RedactedTracePayloadPolicy,
    RetryingStructuredModelClient,
    UsageRecordingStructuredModelClient,
    build_structured_model_client,
)
from personal_agent.capabilities.contracts.model import (
    StructuredModelRequest,
    StructuredModelResponse,
    sealed_context_projection_ref,
)
from personal_agent.capabilities.model_resolution import GovernedModelClient


class ExampleOutput(BaseModel):
    ok: bool


def _request(text: str = "secret") -> StructuredModelRequest[ExampleOutput]:
    messages = [{"role": "user", "content": text}]
    return StructuredModelRequest(
        operation="router",
        version="v1",
        messages=messages,
        output_type=ExampleOutput,
        context_projection_ref=sealed_context_projection_ref(
            purpose="router", messages=messages,
        ),
    )


def test_openai_adapter_uses_chat_completions_json_schema(monkeypatch):
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["init"] = kwargs
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            captured["create"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))],
                model="structured-model",
                usage=SimpleNamespace(
                    prompt_tokens=5,
                    completion_tokens=3,
                    total_tokens=8,
                ),
            )

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    client = OpenAIModelClient(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
    ))

    result = client.generate(_request())

    assert result.value == ExampleOutput(ok=True)
    assert result.input_tokens == 5
    assert result.output_tokens == 3
    assert captured["create"]["response_format"]["type"] == "json_schema"
    assert captured["create"]["response_format"]["json_schema"]["strict"] is True


def test_redacted_policy_removes_message_and_response_bodies():
    policy = RedactedTracePayloadPolicy()
    request = _request("private prompt")
    response = StructuredModelResponse(
        value=ExampleOutput(ok=True),
        model="model",
        latency_ms=2.0,
        content="private output",
        input_tokens=4,
        output_tokens=2,
        total_tokens=6,
    )

    inputs = policy.inputs({"request": request})
    outputs = policy.outputs(response)

    assert "private prompt" not in str(inputs)
    assert inputs["message_chars"] == len("private prompt")
    assert "private output" not in str(outputs)
    assert outputs["response_chars"] == len("private output")


def test_full_policy_exposes_content_without_raw_provider_response():
    policy = FullTracePayloadPolicy()
    request = _request("full prompt")
    response = StructuredModelResponse(
        value=ExampleOutput(ok=True),
        model="model",
        latency_ms=2.0,
        content="full output",
        raw_response=object(),
    )

    inputs = policy.inputs({"request": request})
    outputs = policy.outputs(response)

    assert inputs["messages"][0]["content"] == "full prompt"
    assert outputs["value"] == {"ok": True}
    assert outputs["content"] == "full output"
    assert "raw_response" not in outputs


def test_observation_decorator_applies_policy_without_caller_flags(monkeypatch):
    import langsmith

    captured: dict[str, object] = {}

    class Delegate:
        def generate(self, request, **kwargs):
            captured["request"] = request
            return StructuredModelResponse(
                value=ExampleOutput(ok=True),
                model="model",
                latency_ms=1.0,
            )

    def fake_traceable(**kwargs):
        captured["trace_options"] = kwargs
        return lambda function: function

    monkeypatch.setattr(langsmith, "traceable", fake_traceable)
    policy = RedactedTracePayloadPolicy()
    client = ObservedStructuredModelClient(Delegate(), policy)

    result = client.generate(_request())

    assert result.value.ok is True
    assert captured["trace_options"]["process_inputs"] == policy.inputs
    assert captured["trace_options"]["process_outputs"] == policy.outputs


def test_composition_selects_payload_policy():
    redacted = build_structured_model_client(
        StructuredConfig(api_key="key", base_url="https://llm.invalid"),
        LangSmithConfig(enabled=True, upload_inputs=False),
    )
    full = build_structured_model_client(
        StructuredConfig(api_key="key", base_url="https://llm.invalid"),
        LangSmithConfig(enabled=True, upload_inputs=True),
    )

    assert isinstance(redacted, GovernedModelClient)
    assert isinstance(redacted.transport, ObservedStructuredModelClient)
    assert isinstance(redacted.transport._payload_policy, RedactedTracePayloadPolicy)
    assert isinstance(full, GovernedModelClient)
    assert isinstance(full.transport, ObservedStructuredModelClient)
    assert isinstance(full.transport._payload_policy, FullTracePayloadPolicy)


def test_composition_omits_observer_when_tracing_is_disabled():
    client = build_structured_model_client(
        StructuredConfig(api_key="key", base_url="https://llm.invalid"),
        LangSmithConfig(enabled=False),
    )

    assert isinstance(client, GovernedModelClient)
    assert isinstance(client.transport, UsageRecordingStructuredModelClient)
    assert isinstance(client.transport._delegate, RetryingStructuredModelClient)
    assert isinstance(client.transport._delegate._delegate, OpenAIModelClient)


def test_composition_returns_none_when_model_is_unconfigured():
    assert build_structured_model_client(
        StructuredConfig(api_key=None, base_url=None),
        LangSmithConfig(),
    ) is None


def test_retrying_client_retries_transient_failures():
    calls = 0

    class Delegate:
        def generate(self, request):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionError("Connection error.")
            return StructuredModelResponse(
                value=ExampleOutput(ok=True),
                model="model",
                latency_ms=1.0,
            )

    client = RetryingStructuredModelClient(
        Delegate(),
        max_retries=2,
        backoff_seconds=0,
    )

    result = client.generate(_request())

    assert calls == 2
    assert result.value.ok is True
    assert result.retry_attempts == 1
    assert result.retry_errors == ["Connection error."]


def test_retrying_client_does_not_retry_non_transient_failures():
    calls = 0

    class Delegate:
        def generate(self, request):
            nonlocal calls
            calls += 1
            raise ValueError("structured parse failed")

    client = RetryingStructuredModelClient(
        Delegate(),
        max_retries=2,
        backoff_seconds=0,
    )

    try:
        client.generate(_request())
    except ValueError as exc:
        assert "structured parse failed" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    assert calls == 1
