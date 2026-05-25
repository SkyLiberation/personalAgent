from __future__ import annotations

from types import SimpleNamespace

from personal_agent.agent.runtime_llm import RuntimeLlmMixin
from personal_agent.core.config import Settings


class _Runtime(RuntimeLlmMixin):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings


def test_generate_answer_limits_sdk_waiting(monkeypatch):
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="答案"))]
                    )
                )
            )

    monkeypatch.setattr("personal_agent.agent.runtime_llm.OpenAI", FakeOpenAI)
    runtime = _Runtime(
        Settings(
            openai_api_key="key",
            openai_base_url="https://example.test/v1",
            openai_model="model",
            openai_timeout_seconds=7.0,
            openai_max_retries=0,
        )
    )

    assert runtime._generate_answer("问题") == "答案"
    assert captured["timeout"] == 7.0
    assert captured["max_retries"] == 0


def test_generate_answer_failure_opens_short_circuit(monkeypatch):
    calls = 0

    class FakeOpenAI:
        def __init__(self, **_kwargs: object) -> None:
            nonlocal calls
            calls += 1
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("down")))
            )

    monkeypatch.setattr("personal_agent.agent.runtime_llm.OpenAI", FakeOpenAI)
    runtime = _Runtime(
        Settings(
            openai_api_key="key",
            openai_base_url="https://example.test/v1",
            openai_model="model",
        )
    )

    assert runtime._generate_answer("第一次") is None
    assert runtime._generate_answer("第二次") is None
    assert calls == 1
