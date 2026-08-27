from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import connect
from psycopg import sql

from personal_agent.kernel.config import OpenAIConfig, Settings
from personal_agent.kernel.models import Citation, KnowledgeNote
from personal_agent.infra.storage.postgres_research_store import PostgresResearchStore
from tests.note_factory import make_note

POSTGRES_URL = "postgresql://postgres:postgres@127.0.0.1:5432/personal_agent_test?sslmode=disable"
ADMIN_POSTGRES_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable"


# External-provider env vars that, if populated from a developer's .env, cause
# ordinary tests to make live network calls (with multi-second timeouts,
# retries, provider processes, or trace uploads). Cleared before every test so
# the suite is hermetic and fast. Individual provider tests still inject the
# exact configuration they own after this fixture has run.
_LIVE_PROVIDER_ENV_VARS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "STRUCTURED_API_KEY",
    "STRUCTURED_BASE_URL",
    "STRUCTURED_OUTPUT_TRANSPORT",
    "ROUTER_API_KEY",
    "ROUTER_BASE_URL",
    "PERSONAL_AGENT_EXTRACT_API_KEY",
    "PERSONAL_AGENT_EXTRACT_BASE_URL",
    "PERSONAL_AGENT_GRAPHITI_LLM_API_KEY",
    "PERSONAL_AGENT_GRAPHITI_LLM_BASE_URL",
    "PERSONAL_AGENT_WEB_SEARCH_API_KEY",
    "PERSONAL_AGENT_WEB_SEARCH_BASE_URL",
    "PERSONAL_AGENT_EMBEDDING_API_KEY",
    "PERSONAL_AGENT_EMBEDDING_BASE_URL",
    "PERSONAL_AGENT_MCP_SERVERS",
    "PERSONAL_AGENT_GITHUB_MCP_ENABLED",
    "PERSONAL_AGENT_NOTION_MCP_ENABLED",
    "PERSONAL_AGENT_LANGSMITH_ENABLED",
    "LANGSMITH_TRACING",
    "LANGSMITH_TRACING_V2",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGSMITH_ENDPOINT",
    "LANGSMITH_WORKSPACE_ID",
)


@pytest.fixture(autouse=True)
def _neutralize_live_llm_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ordinary tests from reaching real external providers.

    ``.env`` is loaded into ``os.environ`` by ``Settings.from_env`` through
    ``core.config_env``; once a real key lands in the process
    environment it leaks across tests. This autouse fixture removes those keys
    before every test and neutralizes ``load_dotenv`` so ``from_env`` cannot
    re-import them. Tests that need a configured provider set it explicitly.
    """
    for name in _LIVE_PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    from personal_agent.kernel import config_env as _config_env_module

    monkeypatch.setattr(_config_env_module, "load_dotenv", lambda override=True: False)


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
    PostgresResearchStore(POSTGRES_URL).ensure_schema()
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
                CREATE TABLE IF NOT EXISTS memory_episodes (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    result_contract TEXT NOT NULL,
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
                CREATE TABLE IF NOT EXISTS digest_subscriptions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    schedule_time TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS digest_deliveries (
                    id TEXT PRIMARY KEY,
                    subscription_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    digest_date TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    provider_message_id TEXT,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    sent_at TIMESTAMPTZ
                );
                CREATE TABLE IF NOT EXISTS digest_delivery_items (
                    id TEXT PRIMARY KEY,
                    delivery_id TEXT NOT NULL,
                    short_id TEXT NOT NULL,
                    review_card_id TEXT,
                    note_id TEXT,
                    prompt_snapshot TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_feedback_events (
                    id TEXT PRIMARY KEY,
                    review_card_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    delivery_id TEXT,
                    outcome TEXT NOT NULL,
                    source_channel TEXT NOT NULL,
                    source_message_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_gap_deliveries (
                    idempotency_key TEXT PRIMARY KEY,
                    subscription_id TEXT NOT NULL,
                    gap_date TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS execution_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    step_id TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    payload JSONB NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    created_by_step TEXT NOT NULL DEFAULT '',
                    consumed_by_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
                    user_id TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    expires_at TIMESTAMPTZ,
                    redacted_at TIMESTAMPTZ
                );
                CREATE TABLE IF NOT EXISTS agent_trace_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS resolved_execution_commands (
                    command_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    accepted_intent_ref TEXT NOT NULL,
                    supersedes_command_ref TEXT,
                    authorization_digest TEXT NOT NULL,
                    execution_command_digest TEXT NOT NULL UNIQUE,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS canonical_domain_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE (run_id, task_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS decision_audit_records (
                    audit_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    turn_ref TEXT NOT NULL,
                    proposal_ref TEXT NOT NULL,
                    admission_ref TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    recorded_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS procedure_definitions (
                    procedure_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    spec JSONB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'registered',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (procedure_id, version)
                );
                CREATE TABLE IF NOT EXISTS procedure_deployments (
                    procedure_id TEXT NOT NULL,
                    environment TEXT NOT NULL DEFAULT 'default',
                    stable_version TEXT NOT NULL,
                    canary_version TEXT,
                    canary_percent INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'stable',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (procedure_id, environment)
                );
                CREATE TABLE IF NOT EXISTS execution_replay_runs (
                    replay_id TEXT PRIMARY KEY,
                    source_run_id TEXT NOT NULL,
                    source_thread_id TEXT NOT NULL,
                    source_checkpoint_id TEXT,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    new_run_id TEXT,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS procedure_eval_runs (
                    eval_run_id TEXT PRIMARY KEY,
                    procedure_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    suite TEXT NOT NULL,
                    status TEXT NOT NULL,
                    passed BOOLEAN NOT NULL,
                    score DOUBLE PRECISION,
                    metrics JSONB NOT NULL,
                    report JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS procedure_eval_policies (
                    procedure_id TEXT NOT NULL,
                    environment TEXT NOT NULL DEFAULT 'default',
                    policy JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (procedure_id, environment)
                );
                CREATE TABLE IF NOT EXISTS worker_queue_tasks (
                    task_id TEXT PRIMARY KEY,
                    queue TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    priority INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 1,
                    leased_by TEXT,
                    leased_until TIMESTAMPTZ,
                    due_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    last_error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS knowledge_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_extraction_runs (
                    extraction_run_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_evidence_blocks (
                    evidence_block_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_evidence_spans (
                    evidence_span_id TEXT PRIMARY KEY,
                    evidence_block_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    quote_hash TEXT NOT NULL,
                    text_span TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_claims (
                    claim_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    support_status TEXT NOT NULL,
                    canonical_key TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_grounding_runs (
                    grounding_run_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_claim_support_events (
                    event_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_claim_admission_decisions (
                    admission_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    admission_result TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_state_events (
                    event_id TEXT PRIMARY KEY,
                    target_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    to_state TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_relations (
                    relation_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_items (
                    knowledge_item_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_decisions (
                    decision_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decision_type TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_research_events (
                    research_event_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_review_items (
                    review_item_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    claim_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    priority DOUBLE PRECISION NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_gaps (
                    gap_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    gap_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_graph_projections (
                    graph_projection_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    source_claim_id TEXT NOT NULL,
                    quality_signal TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_projection_jobs (
                    projection_job_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    projection_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_object_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS personal_knowledge_lifecycle_operations (
                    command_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    target_ref TEXT NOT NULL,
                    command_digest TEXT NOT NULL UNIQUE,
                    payload JSONB NOT NULL,
                    status TEXT NOT NULL,
                    confirmation_ref TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL,
                    decided_at TIMESTAMPTZ,
                    UNIQUE (user_id, kind, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS personal_knowledge_lifecycle_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    command_digest TEXT NOT NULL UNIQUE,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    agent_run_id TEXT PRIMARY KEY,
                    submission_key TEXT NOT NULL UNIQUE,
                    definition_digest TEXT NOT NULL,
                    parent_run_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    provider_task_id TEXT,
                    payload JSONB NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                TRUNCATE knowledge_notes, review_cards, memory_episodes, memory_items;
                TRUNCATE tool_idempotency_ledger, tool_audit_events, tool_policy_decisions;
                TRUNCATE digest_subscriptions, digest_deliveries, digest_delivery_items, review_feedback_events;
                TRUNCATE knowledge_gap_deliveries;
                TRUNCATE execution_artifacts;
                TRUNCATE agent_trace_events;
                TRUNCATE resolved_execution_commands, canonical_domain_events, decision_audit_records;
                TRUNCATE procedure_definitions;
                TRUNCATE procedure_deployments;
                TRUNCATE execution_replay_runs;
                TRUNCATE procedure_eval_runs;
                TRUNCATE procedure_eval_policies;
                TRUNCATE worker_queue_tasks;
                TRUNCATE agent_runs;
                TRUNCATE personal_knowledge_lifecycle_receipts, personal_knowledge_lifecycle_operations;
                TRUNCATE knowledge_artifacts, knowledge_extraction_runs, knowledge_evidence_blocks,
                    knowledge_evidence_spans, knowledge_claims, knowledge_grounding_runs,
                    knowledge_claim_support_events, knowledge_claim_admission_decisions,
                    knowledge_state_events, knowledge_relations,
                    knowledge_items, knowledge_decisions,
                    knowledge_research_events, knowledge_review_items, knowledge_gaps,
                    knowledge_graph_projections, knowledge_projection_jobs;
                TRUNCATE research_feedback_events, research_deliveries, intelligence_digests,
                    research_events, research_sources, research_runs, research_subscriptions;
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
