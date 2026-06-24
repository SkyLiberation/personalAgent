from __future__ import annotations

import os
from contextlib import nullcontext
from types import SimpleNamespace

from personal_agent.kernel.config import LangSmithConfig, OpenAIConfig, Settings
from personal_agent.kernel.langsmith_tracing import (
    configure_langsmith_environment,
    langsmith_trace_context,
)
from personal_agent.kernel.llm_trace import (
    LlmTraceResult,
    traced_chat_completion,
)


def test_langsmith_config_reads_env(monkeypatch):
    from personal_agent.kernel import config_env as config_env_module

    monkeypatch.setattr(config_env_module, "load_dotenv", lambda override=True: False)
    monkeypatch.setenv("PERSONAL_AGENT_POSTGRES_URL", "postgresql://example")
    monkeypatch.setenv("PERSONAL_AGENT_LANGSMITH_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://smith.example")
    monkeypatch.setenv("PERSONAL_AGENT_LANGSMITH_PROJECT", "agent-test")
    monkeypatch.setenv("PERSONAL_AGENT_TRACE_UPLOAD_INPUTS", "true")
    monkeypatch.setenv("PERSONAL_AGENT_TRACE_SAMPLE_RATE", "0.25")

    settings = Settings.from_env()

    assert settings.langsmith.enabled is True
    assert settings.langsmith.api_key == "ls-test"
    assert settings.langsmith.endpoint == "https://smith.example"
    assert settings.langsmith.project == "agent-test"
    assert settings.langsmith.upload_inputs is True
    assert settings.langsmith.sample_rate == 0.25


def test_configure_langsmith_environment_sets_standard_vars(monkeypatch):
    for key in (
        "LANGSMITH_TRACING",
        "LANGSMITH_TRACING_V2",
        "LANGSMITH_API_KEY",
        "LANGSMITH_PROJECT",
        "LANGSMITH_ENDPOINT",
        "LANGSMITH_WORKSPACE_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    configure_langsmith_environment(
        LangSmithConfig(
            enabled=True,
            api_key="ls-test",
            project="agent-test",
            endpoint="https://smith.example",
            workspace_id="workspace-1",
        )
    )

    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_TRACING_V2"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "ls-test"
    assert os.environ["LANGSMITH_PROJECT"] == "agent-test"
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://smith.example"
    assert os.environ["LANGSMITH_WORKSPACE_ID"] == "workspace-1"

    configure_langsmith_environment(LangSmithConfig(enabled=False))
    assert os.environ["LANGSMITH_TRACING_V2"] == "false"


def test_disabled_langsmith_environment_forces_tracing_off(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    configure_langsmith_environment(LangSmithConfig(enabled=False))

    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["LANGSMITH_TRACING_V2"] == "false"


def test_langsmith_trace_context_disabled_is_noop():
    ctx = langsmith_trace_context(
        LangSmithConfig(enabled=False),
        metadata={"run_id": "r1"},
    )

    assert isinstance(ctx, nullcontext)


def test_unsampled_trace_context_disables_global_tracer(monkeypatch):
    captured: dict[str, object] = {}

    def fake_tracing_context(**kwargs):
        captured.update(kwargs)
        return nullcontext()

    import langsmith

    monkeypatch.setattr(langsmith, "tracing_context", fake_tracing_context, raising=False)

    # Enabled but sample_rate=0 must actively turn tracing off, otherwise the
    # LANGSMITH_* global tracer keeps emitting runs regardless of sampling.
    langsmith_trace_context(
        LangSmithConfig(enabled=True, sample_rate=0.0),
        metadata={"run_id": "r1"},
    )

    assert captured == {"enabled": False}


def test_langsmith_llm_span_disabled_is_noop():
    from personal_agent.kernel.langsmith_tracing import langsmith_llm_span

    ctx = langsmith_llm_span(
        LangSmithConfig(enabled=False),
        name="llm.stream",
        metadata={"prompt_name": "answer_generation_stream"},
    )

    assert isinstance(ctx, nullcontext)


def test_traced_chat_completion_returns_content_and_metadata(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
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
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"ok": true}')
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=11,
                    completion_tokens=7,
                    total_tokens=18,
                ),
            )

    monkeypatch.setattr("personal_agent.kernel.llm_trace.OpenAI", FakeOpenAI)

    result = traced_chat_completion(
        OpenAIConfig(api_key="key", base_url="https://llm.invalid", small_model="small"),
        prompt_name="router",
        messages=[{"role": "user", "content": "hello"}],
        response_format={"type": "json_object"},
    )

    assert result.content == '{"ok": true}'
    assert result.model == "small"
    assert result.prompt_name == "router"
    assert result.input_tokens == 11
    assert result.output_tokens == 7
    assert result.total_tokens == 18
    assert captured["create"]["response_format"] == {"type": "json_object"}


def test_traced_chat_completion_honors_upload_switch(monkeypatch):
    calls: list[str] = []

    def fake_impl(*args, **kwargs):
        calls.append("impl")
        return LlmTraceResult(
            content="ok",
            model="small",
            latency_ms=1.0,
            prompt_name=kwargs["prompt_name"],
            prompt_version=kwargs["prompt_version"],
        )

    def fake_traced(*args, **kwargs):
        calls.append("traced")
        return LlmTraceResult(
            content="ok",
            model="small",
            latency_ms=1.0,
            prompt_name=kwargs["prompt_name"],
            prompt_version=kwargs["prompt_version"],
        )

    monkeypatch.setattr("personal_agent.kernel.llm_trace._chat_completion_impl", fake_impl)
    monkeypatch.setattr("personal_agent.kernel.llm_trace._traced_chat_completion", fake_traced)
    monkeypatch.setattr("personal_agent.kernel.llm_trace._redacted_traced_chat_completion", fake_impl)
    config = OpenAIConfig(api_key="key", base_url="https://llm.invalid", small_model="small")

    traced_chat_completion(
        config,
        prompt_name="router",
        messages=[{"role": "user", "content": "private"}],
    )
    traced_chat_completion(
        config,
        prompt_name="router",
        messages=[{"role": "user", "content": "private"}],
        upload_inputs_outputs=True,
    )

    assert calls == ["impl", "traced"]


def test_redacted_trace_processors_hide_prompt_content():
    from personal_agent.kernel.llm_trace import (
        LlmTraceResult,
        _redacted_inputs,
        _redacted_outputs,
    )

    inputs = _redacted_inputs({
        "prompt_name": "router",
        "prompt_version": "v1",
        "messages": [{"role": "user", "content": "private prompt"}],
        "model": "small",
        "temperature": 0,
        "max_tokens": 10,
        "metadata": {"source": "intent_router"},
    })
    outputs = _redacted_outputs(LlmTraceResult(
        content="private output",
        model="small",
        latency_ms=1.2,
        prompt_name="router",
        prompt_version="v1",
    ))

    assert inputs["prompt_name"] == "router"
    assert inputs["message_count"] == 1
    assert inputs["message_chars"] == len("private prompt")
    assert "private prompt" not in str(inputs)
    assert outputs["response_chars"] == len("private output")
    assert "private output" not in str(outputs)
