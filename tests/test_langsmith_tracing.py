from __future__ import annotations

import os
from contextlib import nullcontext
from types import SimpleNamespace

from personal_agent.core.config import LangSmithConfig, OpenAIConfig, Settings
from personal_agent.core.langsmith_tracing import (
    configure_langsmith_environment,
    langsmith_trace_context,
)
from personal_agent.core.llm_trace import LlmTraceResult, traced_chat_completion


def test_langsmith_config_reads_env(monkeypatch):
    from personal_agent.core import config as config_module

    monkeypatch.setattr(config_module, "load_dotenv", lambda override=True: False)
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
    assert os.environ["LANGSMITH_API_KEY"] == "ls-test"
    assert os.environ["LANGSMITH_PROJECT"] == "agent-test"
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://smith.example"
    assert os.environ["LANGSMITH_WORKSPACE_ID"] == "workspace-1"

    configure_langsmith_environment(LangSmithConfig(enabled=False))


def test_disabled_langsmith_environment_forces_tracing_off(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    configure_langsmith_environment(LangSmithConfig(enabled=False))

    assert os.environ["LANGSMITH_TRACING"] == "false"


def test_langsmith_trace_context_disabled_is_noop():
    ctx = langsmith_trace_context(
        LangSmithConfig(enabled=False),
        metadata={"run_id": "r1"},
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
                ]
            )

    monkeypatch.setattr("personal_agent.core.llm_trace.OpenAI", FakeOpenAI)

    result = traced_chat_completion(
        OpenAIConfig(api_key="key", base_url="https://llm.invalid", small_model="small"),
        prompt_name="router",
        messages=[{"role": "user", "content": "hello"}],
        response_format={"type": "json_object"},
    )

    assert result.content == '{"ok": true}'
    assert result.model == "small"
    assert result.prompt_name == "router"
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

    monkeypatch.setattr("personal_agent.core.llm_trace._chat_completion_impl", fake_impl)
    monkeypatch.setattr("personal_agent.core.llm_trace._traced_chat_completion", fake_traced)
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
