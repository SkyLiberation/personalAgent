from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import connect
from psycopg import sql

from personal_agent.core.config import Settings
from personal_agent.core.models import Citation, KnowledgeNote

POSTGRES_URL = "postgresql://postgres:postgres@127.0.0.1:5432/personal_agent_test?sslmode=disable"
ADMIN_POSTGRES_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable"


def _ensure_test_database() -> None:
    with connect(ADMIN_POSTGRES_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", ("personal_agent_test",))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier("personal_agent_test")))


@pytest.fixture
def postgres_url() -> str:
    return POSTGRES_URL


@pytest.fixture
def clean_postgres_business_tables():
    _ensure_test_database()
    with PostgresSaver.from_conn_string(POSTGRES_URL) as checkpointer:
        checkpointer.setup()
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_notes (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, parent_note_id TEXT,
                    graph_episode_uuid TEXT, payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_cards (
                    id TEXT PRIMARY KEY, note_id TEXT NOT NULL, payload JSONB NOT NULL,
                    due_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ask_history (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT 'default',
                    question TEXT NOT NULL, answer TEXT NOT NULL, citations JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS pending_actions (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, status TEXT NOT NULL,
                    action_type TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
                    payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cross_session_artifacts (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, artifact_type TEXT NOT NULL,
                    payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
                );
                TRUNCATE knowledge_notes, review_cards, ask_history, pending_actions, cross_session_artifacts;
                TRUNCATE checkpoints, checkpoint_blobs, checkpoint_writes;
                """
            )
        conn.commit()
    yield


@pytest.fixture
def temp_dir() -> Path:
    """Temp directory fixture that works with pytest-asyncio strict mode on Windows."""
    path = Path(tempfile.mkdtemp(prefix="pytest-"))
    yield path
    try:
        shutil.rmtree(path)
    except Exception:
        pass


@pytest.fixture
def settings() -> Settings:
    return Settings(
        data_dir="./data",
        postgres_url=POSTGRES_URL,
        openai_api_key="sk-test-key",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        openai_small_model="gpt-4.1-nano",
    )


@pytest.fixture
def sample_note_factory():
    def _make(
        note_id: str = "note-001",
        title: str = "测试笔记",
        content: str = "这是一篇关于Python单元测试的笔记。",
        summary: str = "Python单元测试入门",
        tags: list[str] | None = None,
    ) -> KnowledgeNote:
        return KnowledgeNote(
            id=note_id,
            title=title,
            content=content,
            summary=summary,
            tags=tags or ["python", "测试"],
        )

    return _make


@pytest.fixture
def sample_note(sample_note_factory) -> KnowledgeNote:
    return sample_note_factory()


@pytest.fixture
def sample_citation_factory():
    def _make(
        note_id: str = "note-001",
        title: str = "测试笔记",
        snippet: str = "Python单元测试...",
        relation_fact: str | None = None,
    ) -> Citation:
        return Citation(
            note_id=note_id,
            title=title,
            snippet=snippet,
            relation_fact=relation_fact,
        )

    return _make


@pytest.fixture
def sample_citation(sample_citation_factory) -> Citation:
    return sample_citation_factory()
