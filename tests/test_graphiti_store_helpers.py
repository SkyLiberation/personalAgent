from __future__ import annotations

from types import SimpleNamespace

import personal_agent.core.config as config_module
from personal_agent.core.config import Settings
from personal_agent.core.models import KnowledgeNote
from personal_agent.graphiti.store import (
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
    monkeypatch.setattr(config_module, "load_dotenv", lambda override: None)
    monkeypatch.setenv("PERSONAL_AGENT_OPENAI_TIMEOUT_SECONDS", "9.5")
    monkeypatch.setenv("PERSONAL_AGENT_OPENAI_MAX_RETRIES", "1")

    settings = Settings.from_env()

    assert settings.openai.timeout_seconds == 9.5
    assert settings.openai.max_retries == 1


def test_settings_reads_graphiti_llm_override_env(monkeypatch):
    monkeypatch.setattr(config_module, "load_dotenv", lambda override: None)
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
    note = KnowledgeNote(title="T", content="abcdef", summary="S")

    assert _graphiti_episode_body(note, max_chars=3) == "abc"


def test_safe_episode_body_removes_urls_and_limits_raw_content():
    note = KnowledgeNote(
        title="T",
        summary="summary with https://example.com/link",
        content="content " * 300,
    )

    body = _graphiti_safe_episode_body(note)

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
