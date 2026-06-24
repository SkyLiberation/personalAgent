"""Shared fixtures for end-to-end orchestration eval tests.

These eval tests exercise the full entry → router → step execution → HITL
interrupt → resume flow against real LangGraph + Postgres infrastructure,
with a deterministic stub standing in for the router LLM. They are kept under
``evals/`` (rather than ``tests/``) because they validate whole-flow behaviour
rather than unit contracts, and they require a running Postgres instance.

Run with:
    uv run pytest evals/test_solidify_clarify_flow.py -v
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from personal_agent.kernel.config import Settings
from tests.conftest import (  # reuse the canonical test infrastructure
    POSTGRES_URL,
    clean_postgres_business_tables,  # noqa: F401 — re-exported fixture
    stub_router_decision,
)


@pytest.fixture
def temp_dir() -> Path:
    """Isolated data dir per test (Windows-safe cleanup)."""
    path = Path(tempfile.mkdtemp(prefix="eval-flow-"))
    yield path
    try:
        shutil.rmtree(path)
    except Exception:
        pass


@pytest.fixture
def stub_settings(temp_dir: Path) -> Settings:
    return Settings(data_dir=temp_dir, postgres_url=POSTGRES_URL)


@pytest.fixture
def runtime(stub_settings: Settings):
    """A real AgentRuntime with the router LLM replaced by a deterministic stub."""
    from personal_agent.agent.runtime import AgentRuntime
    from personal_agent.graphiti.store import GraphitiStore
    from personal_agent.storage.postgres_memory_store import PostgresMemoryStore

    store = PostgresMemoryStore(stub_settings.data_dir, stub_settings.postgres_url)
    runtime = AgentRuntime(
        settings=stub_settings,
        store=store,
        graph_store=GraphitiStore(stub_settings),
    )
    runtime._intent_router._classify_with_llm = stub_router_decision
    return runtime


@pytest.fixture
def api_client(temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """A FastAPI TestClient wired to the same stub router, for HTTP/SSE assertions."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PERSONAL_AGENT_DATA_DIR", str(temp_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("PERSONAL_AGENT_POSTGRES_URL", POSTGRES_URL)
    monkeypatch.setenv("PERSONAL_AGENT_FEISHU_ENABLED", "false")

    from personal_agent.kernel import config_env as config_env_module

    monkeypatch.setattr(config_env_module, "load_dotenv", lambda override=True: False)

    from personal_agent.web.api import create_app

    app = create_app()
    app.state.service.runtime._intent_router._classify_with_llm = stub_router_decision
    return TestClient(app)
