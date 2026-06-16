from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import connect
from psycopg import sql

from personal_agent.core.config import OpenAIConfig, Settings
from personal_agent.core.models import Citation, KnowledgeNote
from personal_agent.agent.router import RouterDecision
from tests.note_factory import make_note

POSTGRES_URL = "postgresql://postgres:postgres@127.0.0.1:5432/personal_agent_test?sslmode=disable"
ADMIN_POSTGRES_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable"


def stub_router_decision(text: str, _messages: list[dict[str, str]] | None = None) -> RouterDecision:
    """Deterministic LLM stand-in for integration tests exercising routed branches."""
    stripped = text.strip()
    if not stripped:
        return RouterDecision(
            route="unknown",
            requires_clarification=True,
            user_visible_message="消息内容为空。",
        )
    if stripped == "帮我":
        return RouterDecision(
            route="unknown",
            requires_clarification=True,
            missing_information=["具体目标或待处理内容"],
            clarification_prompt="请补充具体内容。",
            user_visible_message="需要补充信息。",
        )
    if any(word in stripped for word in ("固化下来", "沉淀下来", "沉淀成", "记下来")):
        return RouterDecision(route="solidify_conversation", user_visible_message="沉淀会话结论。")
    if "删除" in stripped:
        return RouterDecision(
            route="delete_knowledge",
            risk_level="high",
            requires_confirmation=True,
            user_visible_message="删除知识。",
        )
    if "总结" in stripped:
        return RouterDecision(route="summarize_thread", user_visible_message="总结内容。")
    if stripped.startswith(("http://", "https://")):
        return RouterDecision(route="capture_link", user_visible_message="采集链接。")
    if any(word in stripped for word in ("记一下", "记住")):
        return RouterDecision(route="capture_text", user_visible_message="记录内容。")
    if any(word in stripped for word in ("你好", "谢谢", "你是谁")):
        return RouterDecision(route="direct_answer", user_visible_message="直接回答。")
    return RouterDecision(route="ask", user_visible_message="回答问题。")


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
                    deleted_at TIMESTAMPTZ, deleted_by TEXT, delete_reason TEXT,
                    delete_run_id TEXT, delete_checkpoint_id TEXT, delete_snapshot_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_cards (
                    id TEXT PRIMARY KEY, note_id TEXT NOT NULL, payload JSONB NOT NULL,
                    due_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_delete_snapshots (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    target_note_id TEXT NOT NULL,
                    deleted_by TEXT NOT NULL,
                    delete_reason TEXT NOT NULL DEFAULT '',
                    run_id TEXT,
                    checkpoint_id TEXT,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_episodes (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    search_text TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    search_text TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tool_idempotency_ledger (
                    idempotency_key TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    thread_id TEXT,
                    step_id TEXT,
                    tool_call_id TEXT,
                    user_id TEXT,
                    reserved_at TIMESTAMPTZ NOT NULL,
                    committed_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                );
                CREATE TABLE IF NOT EXISTS tool_audit_events (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL,
                    tool_name TEXT NOT NULL,
                    tool_call_id TEXT NOT NULL,
                    thread_id TEXT,
                    step_id TEXT,
                    run_id TEXT,
                    user_id TEXT,
                    execution_mode TEXT NOT NULL,
                    risk_level TEXT,
                    requires_confirmation BOOLEAN,
                    confirmed BOOLEAN,
                    artifact_ok BOOLEAN,
                    error_kind TEXT,
                    error TEXT,
                    latency_ms DOUBLE PRECISION,
                    attempts INTEGER,
                    side_effect_id TEXT,
                    payload JSONB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tool_policy_decisions (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL,
                    action TEXT NOT NULL,
                    effect TEXT NOT NULL,
                    rule TEXT NOT NULL,
                    reason TEXT,
                    tool_name TEXT,
                    permission_scope TEXT,
                    resource TEXT,
                    risk_level TEXT,
                    user_id TEXT,
                    session_id TEXT,
                    source_platform TEXT,
                    execution_mode TEXT,
                    thread_id TEXT,
                    run_id TEXT,
                    langsmith_run_id TEXT
                );
                TRUNCATE knowledge_notes, review_cards, knowledge_delete_snapshots, memory_episodes, memory_items;
                TRUNCATE tool_idempotency_ledger, tool_audit_events, tool_policy_decisions;
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
        openai=OpenAIConfig(
            api_key="sk-test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            small_model="gpt-4.1-nano",
        ),
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
        return make_note(
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
