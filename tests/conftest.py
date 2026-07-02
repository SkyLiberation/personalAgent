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
from personal_agent.planning.router import (
    ClarificationDraft,
    GoalDraft,
    RouterOutput,
)
from tests.note_factory import make_note

POSTGRES_URL = "postgresql://postgres:postgres@127.0.0.1:5432/personal_agent_test?sslmode=disable"
ADMIN_POSTGRES_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable"


# LLM-provider env vars that, if populated from a developer's .env, cause tests
# to make live network calls (with multi-second timeouts + retries). The planner
# endpoint is the worst offender: a single ask/solidify-routed test pays a ~15s
# live SSL round-trip. Cleared session-wide so the suite is hermetic and fast —
# components fall back to offline defaults (planner → default plan, rerank →
# heuristic, etc.). Individual tests still inject stubs/mocks as needed.
_LLM_PROVIDER_ENV_VARS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "STRUCTURED_API_KEY",
    "STRUCTURED_BASE_URL",
    "ROUTER_API_KEY",
    "ROUTER_BASE_URL",
    "PERSONAL_AGENT_PLANNER_API_KEY",
    "PERSONAL_AGENT_PLANNER_BASE_URL",
    "PERSONAL_AGENT_EXTRACT_API_KEY",
    "PERSONAL_AGENT_EXTRACT_BASE_URL",
    "PERSONAL_AGENT_GRAPHITI_LLM_API_KEY",
    "PERSONAL_AGENT_GRAPHITI_LLM_BASE_URL",
    "PERSONAL_AGENT_MS_GRAPHRAG_COMPLETION_API_KEY",
    "PERSONAL_AGENT_MS_GRAPHRAG_EMBEDDING_API_KEY",
    "PERSONAL_AGENT_WEB_SEARCH_API_KEY",
    "PERSONAL_AGENT_WEB_SEARCH_BASE_URL",
    "PERSONAL_AGENT_EMBEDDING_API_KEY",
    "PERSONAL_AGENT_EMBEDDING_BASE_URL",
)


@pytest.fixture(autouse=True)
def _neutralize_live_llm_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite hermetic: no test should hit a real LLM/embedding endpoint.

    ``.env`` is loaded into ``os.environ`` by ``Settings.from_env`` through
    ``core.config_env``; once a real key lands in the process
    environment it leaks across tests. This autouse fixture removes those keys
    before every test and neutralizes ``load_dotenv`` so ``from_env`` cannot
    re-import them. Tests that need a configured provider set it explicitly.
    """
    for name in _LLM_PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    from personal_agent.kernel import config_env as _config_env_module

    monkeypatch.setattr(_config_env_module, "load_dotenv", lambda override=True: False)


def stub_router_decision(text: str, _messages: list[dict[str, str]] | None = None) -> RouterOutput:
    """Deterministic LLM stand-in for integration tests exercising routed branches."""
    stripped = text.strip()
    def decision(intent: str, message: str, **kwargs) -> RouterOutput:
        clarify = bool(kwargs.get("requires_clarification", False))
        unsupported = bool(kwargs.get("unsupported", False))
        route_type = str(kwargs.get("route_type") or (
            "clarify" if clarify
            else "unsupported" if unsupported
            else "direct_answer" if intent == "direct_answer"
            else "single_workflow"
        ))
        outcome = "clarify" if clarify else "unsupported" if unsupported else "ready"
        coverage = str(kwargs.get("coverage") or (
            "ambiguous" if clarify else "unsupported" if unsupported else "full"
        ))
        return RouterOutput(
            user_goal=str(kwargs.get("user_goal") or message),
            route_type=route_type,
            matched_capabilities=list(kwargs.get(
                "matched_capabilities",
                [] if clarify or unsupported else [intent],
            )),
            coverage=coverage,
            missing_requirements=list(kwargs.get("missing_requirements", [])),
            outcome=outcome,
            goals=[] if clarify or unsupported else [GoalDraft(intent=intent, input=stripped)],
            clarification=(
                ClarificationDraft(
                    missing_information=list(
                        kwargs.get(
                            "missing_information",
                            ["明确的目标、问题或操作对象"],
                        )
                    ),
                    prompt=str(kwargs.get("clarification_prompt", message)),
                )
                if clarify else None
            ),
        )
    if not stripped:
        return decision(
            "unknown",
            "消息内容为空。",
            requires_clarification=True,
        )
    if stripped == "帮我":
        return decision(
            "unknown",
            "需要补充信息。",
            requires_clarification=True,
            missing_information=["具体目标或待处理内容"],
            clarification_prompt="请补充具体内容。",
        )
    if any(word in stripped for word in ("记住", "记一下")) and any(
        word in stripped for word in ("然后回答", "再回答", "并回答")
    ):
        return RouterOutput(
            user_goal="记录一条知识并基于该主题回答后续问题",
            route_type="composite_workflow",
            matched_capabilities=["capture_text", "ask"],
            coverage="full",
            missing_requirements=[],
            outcome="ready",
            goals=[
                GoalDraft(intent="capture_text", input=stripped),
                GoalDraft(intent="ask", input=stripped),
            ],
            clarification=None,
        )
    if any(word in stripped for word in ("固化下来", "沉淀下来", "沉淀成", "记下来")):
        return decision("solidify_conversation", "沉淀会话结论。")
    if "删除" in stripped:
        return decision(
            "delete_knowledge",
            "删除知识。",
            risk_level="high",
            requires_confirmation=True,
        )
    if "总结" in stripped:
        return decision("summarize_thread", "总结内容。")
    if "知识简报" in stripped or "复习简报" in stripped:
        return decision("review_digest", "生成知识简报。")
    if any(word in stripped for word in ("整理成综述", "合并笔记", "整理知识")):
        return decision("consolidate_knowledge", "按主题整理知识。")
    if any(word in stripped for word in ("知识缺口", "知识孤岛", "检查缺口")):
        return decision("inspect_knowledge_gaps", "检查知识缺口。")
    if any(word in stripped for word in ("暂停订阅", "恢复订阅", "修改订阅", "改成每天", "马上跑一次", "最近几次简报")):
        return decision("manage_research", "管理研究订阅。")
    if any(word in stripped for word in ("知识过期", "替换这条", "冲突", "修正笔记", "更新笔记")):
        return decision("maintain_knowledge", "维护已有知识。")
    if any(word in stripped for word in ("worker", "队列", "失败任务", "没发", "重试任务")):
        return decision("inspect_operations", "诊断后台任务。")
    if any(word in stripped for word in ("run_id", "执行历史", "哪一步失败", "workflow")):
        return decision("inspect_workflow", "诊断 workflow。")
    if any(word in stripped for word in ("发到邮箱", "发送邮件", "剪成短视频", "生成PPT", "生成 PPT")):
        return decision(
            "unknown",
            "当前能力无法完整覆盖该请求。",
            unsupported=True,
            coverage="partial",
            matched_capabilities=["analyze_artifact"] if "音频" in stripped or "图片" in stripped else [],
            missing_requirements=["缺少文件生成、视频编辑或邮件发送能力"],
            user_goal="完成当前未注册能力覆盖的跨应用处理",
        )
    if any(word in stripped for word in ("每天", "每周", "工作日")) and any(
        word in stripped for word in ("新闻", "资讯", "动态", "简报", "跟踪")
    ):
        return decision("create_research_subscription", "创建研究订阅。")
    research_cues = (
        "最新", "最近", "多来源", "多源", "高可信", "官方", "整理", "最多",
        "不超过", "简报", "动态", "发布", "趋势", "发展", "进展", "新闻",
        "公告", "论文", "开源", "财报", "报告", "GitHub", "github",
    )
    simple_qa_cues = (
        "什么是", "什么叫", "是什么", "是多少", "解释一下", "介绍一下",
        "如何", "怎么", "为什么", "是否", "区别",
    )
    if (
        any(word in stripped for word in ("调研", "研究一下", "研究最近", "搜集最新", "搜集最近", "收集最新", "收集最近", "关注"))
        and any(word in stripped for word in research_cues)
    ) or (
        any(word in stripped for word in ("查一下", "帮我查", "查询"))
        and any(word in stripped for word in research_cues)
        and not any(word in stripped for word in simple_qa_cues)
    ):
        return decision("research_once", "执行一次研究。")
    if stripped.startswith(("http://", "https://")):
        return decision("capture_link", "采集链接。")
    if any(word in stripped for word in ("记一下", "记住")):
        return decision("capture_text", "记录内容。")
    if any(word in stripped for word in ("你好", "谢谢", "你是谁")):
        return decision("direct_answer", "直接回答。")
    return decision("ask", "回答问题。")


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
                CREATE TABLE IF NOT EXISTS workflow_artifacts (
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
                CREATE TABLE IF NOT EXISTS workflow_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS workflow_definitions (
                    workflow_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    spec JSONB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'registered',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (workflow_id, version)
                );
                CREATE TABLE IF NOT EXISTS workflow_deployments (
                    workflow_id TEXT NOT NULL,
                    environment TEXT NOT NULL DEFAULT 'default',
                    stable_version TEXT NOT NULL,
                    canary_version TEXT,
                    canary_percent INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'stable',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (workflow_id, environment)
                );
                CREATE TABLE IF NOT EXISTS workflow_replay_runs (
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
                CREATE TABLE IF NOT EXISTS workflow_eval_runs (
                    eval_run_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    suite TEXT NOT NULL,
                    status TEXT NOT NULL,
                    passed BOOLEAN NOT NULL,
                    score DOUBLE PRECISION,
                    metrics JSONB NOT NULL,
                    report JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS workflow_eval_policies (
                    workflow_id TEXT NOT NULL,
                    environment TEXT NOT NULL DEFAULT 'default',
                    policy JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (workflow_id, environment)
                );
                CREATE TABLE IF NOT EXISTS workflow_state_migrations (
                    workflow_id TEXT NOT NULL,
                    from_version TEXT NOT NULL,
                    to_version TEXT NOT NULL,
                    step_mapping JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (workflow_id, from_version, to_version)
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
                TRUNCATE knowledge_notes, review_cards, knowledge_delete_snapshots, memory_episodes, memory_items;
                TRUNCATE tool_idempotency_ledger, tool_audit_events, tool_policy_decisions;
                TRUNCATE digest_subscriptions, digest_deliveries, digest_delivery_items, review_feedback_events;
                TRUNCATE knowledge_gap_deliveries;
                TRUNCATE workflow_artifacts;
                TRUNCATE workflow_events;
                TRUNCATE workflow_definitions;
                TRUNCATE workflow_deployments;
                TRUNCATE workflow_replay_runs;
                TRUNCATE workflow_eval_runs;
                TRUNCATE workflow_eval_policies;
                TRUNCATE workflow_state_migrations;
                TRUNCATE worker_queue_tasks;
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
