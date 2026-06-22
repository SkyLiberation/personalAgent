from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from personal_agent.core.config_models import LangSmithConfig, RouterConfig
from personal_agent.core.structured_model import (
    FullTracePayloadPolicy,
    ObservedStructuredModelClient,
    OpenAIResponsesModelClient,
    RedactedTracePayloadPolicy,
    StructuredModelRequest,
    StructuredModelResponse,
    build_structured_model_client,
)


class ExampleOutput(BaseModel):
    ok: bool


def _request(text: str = "secret") -> StructuredModelRequest[ExampleOutput]:
    return StructuredModelRequest(
        operation="router",
        version="v1",
        messages=[{"role": "user", "content": text}],
        output_type=ExampleOutput,
    )


def test_openai_adapter_uses_responses_parse(monkeypatch):
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["init"] = kwargs
            self.responses = SimpleNamespace(parse=self._parse)

        def _parse(self, **kwargs):
            captured["parse"] = kwargs
            return SimpleNamespace(
                output_parsed=ExampleOutput(ok=True),
                output_text='{"ok":true}',
                model="structured-model",
                status="completed",
                usage=SimpleNamespace(
                    input_tokens=5,
                    output_tokens=3,
                    total_tokens=8,
                ),
            )

    monkeypatch.setattr("personal_agent.core.structured_model.OpenAI", FakeOpenAI)
    client = OpenAIResponsesModelClient(RouterConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
    ))

    result = client.generate(_request())

    assert result.value == ExampleOutput(ok=True)
    assert result.input_tokens == 5
    assert result.output_tokens == 3
    assert captured["parse"]["text_format"] is ExampleOutput
    assert "response_format" not in captured["parse"]


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
        RouterConfig(api_key="key", base_url="https://llm.invalid"),
        LangSmithConfig(enabled=True, upload_inputs=False),
    )
    full = build_structured_model_client(
        RouterConfig(api_key="key", base_url="https://llm.invalid"),
        LangSmithConfig(enabled=True, upload_inputs=True),
    )

    assert isinstance(redacted, ObservedStructuredModelClient)
    assert isinstance(redacted._payload_policy, RedactedTracePayloadPolicy)
    assert isinstance(full, ObservedStructuredModelClient)
    assert isinstance(full._payload_policy, FullTracePayloadPolicy)


def test_composition_omits_observer_when_tracing_is_disabled():
    client = build_structured_model_client(
        RouterConfig(api_key="key", base_url="https://llm.invalid"),
        LangSmithConfig(enabled=False),
    )

    assert isinstance(client, OpenAIResponsesModelClient)


def test_composition_returns_none_when_model_is_unconfigured():
    assert build_structured_model_client(
        RouterConfig(api_key=None, base_url=None),
        LangSmithConfig(),
    ) is None
