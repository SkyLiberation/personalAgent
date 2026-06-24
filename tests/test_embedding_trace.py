from __future__ import annotations

from types import SimpleNamespace

from personal_agent.kernel.embedding_trace import EmbeddingTraceResult, traced_embedding
from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore


def test_traced_embedding_returns_vector_and_metadata(monkeypatch):
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["init"] = kwargs
            self.embeddings = SimpleNamespace(create=self._create)

        def _create(self, **kwargs):
            captured["create"] = kwargs
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])]
            )

    monkeypatch.setattr("personal_agent.kernel.embedding_trace.OpenAI", FakeOpenAI)

    result = traced_embedding(
        api_key="key",
        base_url="https://embedding.invalid",
        model="embed-model",
        text="hello",
        timeout_seconds=7.0,
    )

    assert isinstance(result, EmbeddingTraceResult)
    assert result.vector == [0.1, 0.2, 0.3]
    assert result.model == "embed-model"
    assert result.input_chars == 5
    assert captured["init"]["api_key"] == "key"
    assert captured["init"]["base_url"] == "https://embedding.invalid"
    assert captured["init"]["timeout"] == 7.0
    assert captured["create"] == {"model": "embed-model", "input": "hello"}


def test_postgres_store_embedding_falls_back_to_local_on_external_failure_with_patch(
    temp_dir,
    monkeypatch,
):
    class BrokenOpenAI:
        def __init__(self, **_kwargs):
            self.embeddings = SimpleNamespace(create=self._create)

        def _create(self, **_kwargs):
            raise RuntimeError("down")

    monkeypatch.setattr("personal_agent.kernel.embedding_trace.OpenAI", BrokenOpenAI)
    store = PostgresMemoryStore(
        temp_dir,
        "postgresql://example.invalid/db",
        embedding_provider="openai",
        embedding_model="embed-model",
        embedding_api_key="key",
        embedding_base_url="https://embedding.invalid",
    )

    vector = store._embed_text("fallback text")  # noqa: SLF001

    assert vector is not None
    assert len(vector) == 128
