from __future__ import annotations

import json
from dataclasses import replace
from threading import Event
from time import perf_counter
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from personal_agent.kernel.config_models import LangSmithConfig, StructuredConfig
from personal_agent.infra.structured_model import (
    FullTracePayloadPolicy,
    JsonObjectStructuredAdapter,
    ModelCallDeadlineExceeded,
    ObservedStructuredModelClient,
    StrictJsonSchemaAdapter as OpenAIModelClient,
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
    assert captured["init"]["max_retries"] == 0
    assert captured["create"]["response_format"]["type"] == "json_schema"
    assert captured["create"]["response_format"]["json_schema"]["strict"] is True


def test_openai_adapter_enforces_total_provider_deadline(monkeypatch):
    closed = Event()

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **_kwargs):
            closed.wait(timeout=2)
            raise RuntimeError("provider connection closed")

        def close(self):
            closed.set()

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    client = OpenAIModelClient(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
        timeout_seconds=0.05,
        max_retries=0,
    ))

    started = perf_counter()
    with pytest.raises(ModelCallDeadlineExceeded, match="router provider call exceeded"):
        client.generate(_request())

    assert perf_counter() - started < 0.5
    assert closed.wait(timeout=0.5)


def test_openai_adapter_sends_typed_effort_only_to_reasoning_models(monkeypatch):
    calls: list[dict[str, object]] = []

    class FakeOpenAI:
        def __init__(self, **_):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))],
                model=kwargs["model"],
                usage=None,
            )

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    request = replace(_request(), max_tokens=6000, reasoning_effort="low")

    OpenAIModelClient(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="gpt-5.4-mini",
    )).generate(request)
    OpenAIModelClient(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="non-reasoning-model",
    )).generate(request)

    assert calls[0]["max_completion_tokens"] == 6000
    assert calls[0]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in calls[1]


def test_openai_adapter_accepts_direct_structured_content_transport(monkeypatch):
    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_: '{"ok":true}')
            )

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    client = OpenAIModelClient(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
        max_retries=7,
    ))

    result = client.generate(_request())

    assert result.value == ExampleOutput(ok=True)
    assert result.content == '{"ok":true}'


def test_openai_adapter_unwraps_nested_chat_completion_envelope(monkeypatch):
    nested_envelope = json.dumps({
        "id": "nested-completion",
        "object": "chat.completion",
        "model": "provider-model",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": '{"ok":true}'},
            "finish_reason": "stop",
        }],
    })

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(
                        content=nested_envelope,
                        tool_calls=None,
                    ))],
                    model="structured-model",
                    usage=None,
                ))
            )

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    client = OpenAIModelClient(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
    ))

    result = client.generate(_request())

    assert result.value == ExampleOutput(ok=True)
    assert result.content == '{"ok":true}'


def test_strict_adapter_repairs_empty_nested_completion_without_downgrade(monkeypatch):
    calls: list[dict[str, object]] = []
    empty_nested_envelope = json.dumps({
        "id": "nested-completion",
        "object": "chat.completion",
        "choices": [],
    })

    class FakeOpenAI:
        def __init__(self, **_):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            calls.append(kwargs)
            content = empty_nested_envelope if len(calls) == 1 else '{"ok":true}'
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    content=content,
                    tool_calls=None,
                ))],
                model="structured-model",
                usage=None,
            )

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    client = OpenAIModelClient(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
    ))

    result = client.generate(_request())
    cached_result = client.generate(_request("second request"))

    assert result.value == ExampleOutput(ok=True)
    assert cached_result.value == ExampleOutput(ok=True)
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[1]["response_format"]["type"] == "json_schema"
    assert calls[2]["response_format"]["type"] == "json_schema"
    assert len(calls) == 3


def test_strict_adapter_fails_closed_after_one_invalid_repair(monkeypatch):
    calls: list[dict[str, object]] = []
    empty_nested_envelope = json.dumps({
        "id": "nested-completion",
        "object": "chat.completion",
        "choices": [],
    })

    class FakeOpenAI:
        def __init__(self, **_):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            calls.append(kwargs)
            content = empty_nested_envelope
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    content=content,
                    tool_calls=None,
                ))],
                model="structured-model",
                usage=None,
            )

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    client = OpenAIModelClient(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
    ))

    with pytest.raises(ValueError, match="structured parse failed"):
        client.generate(_request())

    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[1]["response_format"]["type"] == "json_schema"
    assert len(calls) == 2


def test_openai_adapter_switches_to_streaming_after_provider_returns_sse(monkeypatch):
    calls: list[dict[str, object]] = []
    sse_without_content = (
        'data: {"object":"chat.completion.chunk","choices":[]}\n\n'
        "data: [DONE]\n\n"
    )

    class FakeOpenAI:
        def __init__(self, **_):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            calls.append(kwargs)
            if not kwargs.get("stream"):
                return sse_without_content
            return iter([
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content='{"ok":'))],
                    model="structured-model",
                    usage=None,
                ),
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="true}"))],
                    model="structured-model",
                    usage=None,
                ),
            ])

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    client = OpenAIModelClient(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
    ))

    result = client.generate(_request())
    cached_result = client.generate(_request("second request"))

    assert result.value == ExampleOutput(ok=True)
    assert cached_result.value == ExampleOutput(ok=True)
    assert calls[0].get("stream") is None
    assert calls[1]["stream"] is True
    assert calls[2]["stream"] is True
    assert len(calls) == 3


def test_openai_adapter_deadline_covers_structured_stream_consumption(monkeypatch):
    closed = Event()
    sse_without_content = (
        'data: {"object":"chat.completion.chunk","choices":[]}\n\n'
        "data: [DONE]\n\n"
    )

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            if not kwargs.get("stream"):
                return sse_without_content

            def drip_chunks():
                while not closed.wait(timeout=0.005):
                    yield SimpleNamespace(
                        choices=[],
                        model="structured-model",
                        usage=None,
                    )

            return drip_chunks()

        def close(self):
            closed.set()

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    client = OpenAIModelClient(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
        timeout_seconds=0.05,
        max_retries=0,
    ))

    started = perf_counter()
    with pytest.raises(ModelCallDeadlineExceeded, match="router provider call exceeded"):
        client.generate(_request())

    assert perf_counter() - started < 0.5
    assert closed.wait(timeout=0.5)


def test_openai_adapter_unwraps_string_encoded_nested_choice_and_message(monkeypatch):
    nested_envelope = json.dumps({
        "id": "nested-completion",
        "object": "chat.completion",
        "model": "provider-model",
        "choices": json.dumps([json.dumps({
            "index": 0,
            "message": json.dumps({
                "role": "assistant",
                "content": '{"ok":true}',
            }),
            "finish_reason": "stop",
        })]),
    })

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_: nested_envelope)
            )

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    client = OpenAIModelClient(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
    ))

    result = client.generate(_request())

    assert result.value == ExampleOutput(ok=True)
    assert result.content == '{"ok":true}'


def test_openai_adapter_unwraps_fenced_nested_completion_envelope(monkeypatch):
    nested_envelope = "```json\n" + json.dumps({
        "id": "nested-completion",
        "object": "chat.completion",
        "model": "provider-model",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": '{"ok":true}'},
            "finish_reason": "stop",
        }],
    }) + "\n```"

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(
                        content=nested_envelope,
                        tool_calls=None,
                    ))],
                    model="structured-model",
                    usage=None,
                ))
            )

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    client = OpenAIModelClient(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
    ))

    result = client.generate(_request())

    assert result.value == ExampleOutput(ok=True)
    assert result.content == '{"ok":true}'


def test_strict_adapter_does_not_downgrade_when_json_schema_is_unavailable(monkeypatch):
    calls: list[dict[str, object]] = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError("response_format type is unavailable now")

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    client = OpenAIModelClient(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
    ))

    with pytest.raises(RuntimeError, match="response_format type is unavailable"):
        client.generate(_request())

    assert len(calls) == 1
    assert calls[0]["response_format"]["type"] == "json_schema"


def test_json_object_adapter_repairs_incomplete_json_and_aggregates_usage(monkeypatch):
    calls: list[dict[str, object]] = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            calls.append(kwargs)
            content = "{}" if len(calls) == 1 else '{"ok":true}'
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                model="structured-model",
                usage=SimpleNamespace(
                    prompt_tokens=5,
                    completion_tokens=3,
                    total_tokens=8,
                ),
            )

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    client = JsonObjectStructuredAdapter(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
    ))

    result = client.generate(_request())

    assert result.value == ExampleOutput(ok=True)
    assert result.input_tokens == 10
    assert result.output_tokens == 6
    assert result.total_tokens == 16
    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[1]["response_format"] == {"type": "json_object"}
    assert "Output schema" in calls[0]["messages"][0]["content"]
    assert "previous structured response was rejected" in calls[1]["messages"][0]["content"]
    assert "Never repeat a value identified as invalid" in (
        calls[1]["messages"][0]["content"]
    )
    assert "omit that item" in calls[1]["messages"][0]["content"]


def test_json_object_adapter_fails_closed_after_one_empty_repair(monkeypatch):
    calls: list[dict[str, object]] = []

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=""))],
                model="structured-model",
                usage=None,
            )

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    client = JsonObjectStructuredAdapter(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
        output_transport="json_object",
    ))

    with pytest.raises(ValueError, match="empty structured content"):
        client.generate(_request())

    assert len(calls) == 2
    assert all(call["response_format"] == {"type": "json_object"} for call in calls)


def test_openai_adapter_asks_model_to_reauthor_cross_field_invalid_json(monkeypatch):
    calls: list[dict[str, object]] = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            calls.append(kwargs)
            content = '{"ok":"not-a-bool"}' if len(calls) == 1 else '{"ok":true}'
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                model="structured-model",
                usage=None,
            )

    monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)
    client = OpenAIModelClient(StructuredConfig(
        api_key="key",
        base_url="https://llm.invalid",
        model="structured-model",
    ))

    result = client.generate(_request())

    assert result.value == ExampleOutput(ok=True)
    assert len(calls) == 2
    assert calls[1]["response_format"]["type"] == "json_schema"
    assert "previous structured response was rejected" in calls[1]["messages"][0]["content"]


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
    assert client.transport._delegate._backoff_seconds == 2.0
    assert isinstance(client.transport._delegate._delegate, OpenAIModelClient)


def test_composition_selects_json_object_adapter_from_provider_profile():
    client = build_structured_model_client(
        StructuredConfig(
            api_key="key",
            base_url="https://llm.invalid",
            output_transport="json_object",
        ),
        LangSmithConfig(enabled=False),
    )

    assert isinstance(client, GovernedModelClient)
    assert isinstance(client.transport, UsageRecordingStructuredModelClient)
    assert isinstance(client.transport._delegate, RetryingStructuredModelClient)
    assert isinstance(
        client.transport._delegate._delegate,
        JsonObjectStructuredAdapter,
    )


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


def test_retrying_client_retries_malformed_success_transport():
    calls = 0

    class Delegate:
        def generate(self, request):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError(
                    "invalid provider response: missing chat completion choices"
                )
            return StructuredModelResponse(
                value=ExampleOutput(ok=True),
                model="model",
                latency_ms=1.0,
            )

    client = RetryingStructuredModelClient(
        Delegate(),
        max_retries=1,
        backoff_seconds=0,
    )

    result = client.generate(_request())

    assert calls == 2
    assert result.retry_attempts == 1


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
