from __future__ import annotations

from types import SimpleNamespace

import personal_agent.kernel.config_env as config_env_module
from personal_agent.kernel.config import Settings
from personal_agent.kernel.projections import graph_ingest_document_from_note
from tests.note_factory import make_note
from personal_agent.memory.graphiti.store import (
    GraphitiStore,
    _graphiti_episode_body,
    _graphiti_safe_episode_body,
    _looks_like_content_filter_error,
    _episode_uuids_from_search_result,
)


def test_settings_reads_graphiti_timeout_env(monkeypatch):
    monkeypatch.setenv("PERSONAL_AGENT_GRAPHITI_ADD_EPISODE_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("PERSONAL_AGENT_GRAPHITI_SEARCH_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("PERSONAL_AGENT_GRAPHITI_EPISODE_MAX_CHARS", "99")
    monkeypatch.setenv("PERSONAL_AGENT_GRAPHITI_CONTENT_FILTER_FALLBACK", "false")
    monkeypatch.setenv("PERSONAL_AGENT_GRAPH_SYNC_MAX_WORKERS", "7")
    monkeypatch.setenv("PERSONAL_AGENT_GRAPH_SYNC_MAX_NOTES_PER_CAPTURE", "11")
    monkeypatch.setenv("PERSONAL_AGENT_GRAPH_SEARCH_CITATION_LIMIT", "17")

    settings = Settings.from_env()

    assert settings.graphiti.add_episode_timeout_seconds == 12.5
    assert settings.graphiti.search_timeout_seconds == 3
    assert settings.graphiti.episode_max_chars == 99
    assert settings.graphiti.content_filter_fallback is False
    assert settings.graphiti.sync_max_workers == 7
    assert settings.graphiti.sync_max_notes_per_capture == 11
    assert settings.graphiti.search_citation_limit == 17


def test_settings_reads_openai_request_limits(monkeypatch):
    monkeypatch.setattr(config_env_module, "load_dotenv", lambda override: None)
    monkeypatch.setenv("PERSONAL_AGENT_OPENAI_TIMEOUT_SECONDS", "9.5")
    monkeypatch.setenv("PERSONAL_AGENT_OPENAI_MAX_RETRIES", "1")

    settings = Settings.from_env()

    assert settings.openai.timeout_seconds == 9.5
    assert settings.openai.max_retries == 1


def test_settings_prefers_structured_llm_over_router_env(monkeypatch):
    monkeypatch.setattr(config_env_module, "load_dotenv", lambda override: None)
    monkeypatch.setenv("ROUTER_API_KEY", "router-key")
    monkeypatch.setenv("ROUTER_BASE_URL", "https://router.example/v1")
    monkeypatch.setenv("ROUTER_MODEL", "router-model")
    monkeypatch.setenv("STRUCTURED_API_KEY", "structured-key")
    monkeypatch.setenv("STRUCTURED_BASE_URL", "https://structured.example/v1")
    monkeypatch.setenv("STRUCTURED_MODEL", "structured-model")
    monkeypatch.setenv("STRUCTURED_OUTPUT_TRANSPORT", "json_object")
    monkeypatch.setenv(
        "STRUCTURED_EXTRA_BODY",
        '{"reasoning":{"effort":"minimal"}}',
    )

    settings = Settings.from_env()

    assert settings.structured.api_key == "structured-key"
    assert settings.structured.base_url == "https://structured.example/v1"
    assert settings.structured.model == "structured-model"
    assert settings.structured.output_transport == "json_object"
    assert settings.structured.extra_body == {"reasoning": {"effort": "minimal"}}


def test_settings_preserves_injected_environment_when_dotenv_is_disabled(monkeypatch):
    def forbidden_load(*, override):
        raise AssertionError(f"load_dotenv must not run with override={override}")

    monkeypatch.setattr(config_env_module, "load_dotenv", forbidden_load)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "true")
    monkeypatch.setenv("STRUCTURED_API_KEY", "isolated-key")
    monkeypatch.setenv("STRUCTURED_BASE_URL", "https://isolated.example/v1")
    monkeypatch.setenv("STRUCTURED_MODEL", "isolated-model")

    settings = Settings.from_env()

    assert settings.structured.api_key == "isolated-key"
    assert settings.structured.base_url == "https://isolated.example/v1"
    assert settings.structured.model == "isolated-model"


def test_structured_provider_is_default_for_every_generative_adapter(monkeypatch):
    monkeypatch.setattr(config_env_module, "load_dotenv", lambda override: None)
    monkeypatch.setenv("STRUCTURED_API_KEY", "canonical-key")
    monkeypatch.setenv("STRUCTURED_BASE_URL", "https://canonical.example/v1")
    monkeypatch.setenv("STRUCTURED_MODEL", "gpt-5.6-terra")
    monkeypatch.setenv("EMBEDDING_API_KEY", "embedding-key")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embedding.example/v1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "local-multilingual-384")
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "OPENAI_SMALL_MODEL",
        "PERSONAL_AGENT_GRAPHITI_LLM_API_KEY",
        "PERSONAL_AGENT_GRAPHITI_LLM_BASE_URL",
        "PERSONAL_AGENT_GRAPHITI_LLM_MODEL",
        "PERSONAL_AGENT_GRAPHITI_LLM_SMALL_MODEL",
        "PERSONAL_AGENT_EXTRACT_API_KEY",
        "PERSONAL_AGENT_EXTRACT_BASE_URL",
        "PERSONAL_AGENT_EXTRACT_MODEL",
        "PERSONAL_AGENT_MS_GRAPHRAG_COMPLETION_API_KEY",
        "PERSONAL_AGENT_MS_GRAPHRAG_COMPLETION_API_BASE",
        "PERSONAL_AGENT_MS_GRAPHRAG_COMPLETION_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    expected_provider = (
        "canonical-key",
        "https://canonical.example/v1",
        "gpt-5.6-terra",
    )
    assert (
        settings.openai.api_key,
        settings.openai.base_url,
        settings.openai.model,
    ) == expected_provider
    assert settings.openai.small_model == "gpt-5.6-terra"
    assert (
        settings.graphiti.llm_api_key,
        settings.graphiti.llm_base_url,
        settings.graphiti.llm_model,
    ) == expected_provider
    assert settings.graphiti.llm_small_model == "gpt-5.6-terra"
    assert (
        settings.langextract.api_key,
        settings.langextract.base_url,
        settings.langextract.model_id,
    ) == expected_provider
    assert (
        settings.ms_graphrag.completion_api_key,
        settings.ms_graphrag.completion_api_base,
        settings.ms_graphrag.completion_model,
    ) == expected_provider
    assert settings.openai.embedding_api_key == "embedding-key"
    assert settings.openai.embedding_base_url == "https://embedding.example/v1"
    assert settings.openai.embedding_model == "local-multilingual-384"


def test_settings_reads_graphiti_llm_override_env(monkeypatch):
    monkeypatch.setattr(config_env_module, "load_dotenv", lambda override: None)
    monkeypatch.setenv("PERSONAL_AGENT_GRAPHITI_LLM_API_KEY", "graph-key")
    monkeypatch.setenv(
        "PERSONAL_AGENT_GRAPHITI_LLM_BASE_URL", "https://graph.example/v1"
    )
    monkeypatch.setenv("PERSONAL_AGENT_GRAPHITI_LLM_MODEL", "graph-model")
    monkeypatch.setenv("PERSONAL_AGENT_GRAPHITI_LLM_SMALL_MODEL", "graph-small-model")

    settings = Settings.from_env()

    assert settings.graphiti.llm_api_key == "graph-key"
    assert settings.graphiti.llm_base_url == "https://graph.example/v1"
    assert settings.graphiti.llm_model == "graph-model"
    assert settings.graphiti.llm_small_model == "graph-small-model"


def test_graphiti_episode_body_honors_max_chars():
    note = make_note(title="T", content="abcdef", summary="S")

    assert _graphiti_episode_body(graph_ingest_document_from_note(note), max_chars=3) == "abc"


def test_safe_episode_body_removes_urls_and_limits_raw_content():
    note = make_note(
        title="T",
        summary="summary with https://example.com/link",
        content="content " * 300,
    )

    body = _graphiti_safe_episode_body(graph_ingest_document_from_note(note))

    assert "https://" not in body
    assert body.startswith("Title: T")
    assert len(body) < 2200


def test_content_filter_error_detection_supports_provider_messages():
    assert _looks_like_content_filter_error(Exception("400 high risk content"))
    assert _looks_like_content_filter_error(Exception("content_filter blocked"))
    assert not _looks_like_content_filter_error(Exception("connection timed out"))


def test_episode_uuids_from_search_result_dedupes_raw_episodes():
    result = SimpleNamespace(
        episodes=[
            SimpleNamespace(uuid="ep-1"),
            SimpleNamespace(uuid="ep-2"),
            SimpleNamespace(uuid="ep-1"),
            SimpleNamespace(uuid=""),
        ]
    )

    assert _episode_uuids_from_search_result(result) == ["ep-1", "ep-2"]


def test_close_client_closes_http_clients_and_driver():
    import asyncio

    closed: list[str] = []

    class AsyncClient:
        async def close(self):
            closed.append("http")

    class Graphiti:
        llm_client = SimpleNamespace(client=AsyncClient())
        embedder = SimpleNamespace(client=AsyncClient())
        cross_encoder = None

        async def close(self):
            closed.append("driver")

    asyncio.run(GraphitiStore._close_client(Graphiti()))

    assert closed == ["http", "http", "driver"]
