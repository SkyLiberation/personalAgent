from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from personal_agent.application.research import (
    DeliveryTarget,
    ResearchBudget,
    ResearchFeedback,
    ResearchScheduler,
    ResearchService,
    ResearchSubscription,
    SchedulePolicy,
    subscription_due,
)
from personal_agent.application.research.models import (
    EvidenceGap,
    PersonalRelevance,
    ResearchDecision,
    ResearchEvent,
    ResearchPolicy,
    ResearchRun,
    ResearchSource,
    ResearchState,
)
from personal_agent.infra.storage.postgres_research_store import PostgresResearchStore
from personal_agent.infra.storage.postgres_worker_queue_store import PostgresWorkerQueueStore
from personal_agent.application.worker import WorkflowWorker

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


class FakeTools:
    def __contains__(self, name: str) -> bool:
        return name in {"web_search", "capture_url", "graph_search"}

    def invoke_direct(self, name: str, **kwargs):
        if name == "web_search":
            return {
                "ok": True,
                "data": {
                    "results": [
                        {
                            "title": "OpenAI releases Agent Model",
                            "url": "https://openai.com/news/agent?utm_source=test",
                            "snippet": "OpenAI released a new agent model.",
                            "source": "fake",
                            "published_at": "2026-06-23T01:00:00Z",
                        },
                        {
                            "title": "OpenAI releases Agent Model",
                            "url": "https://news.example/openai-agent",
                            "snippet": "Independent report about the same release.",
                            "source": "fake",
                            "published_at": "2026-06-23T02:00:00Z",
                        },
                    ]
                },
            }
        if name == "capture_url":
            return {"ok": True, "data": {"text": "Full source text about the model release."}}
        if name == "graph_search":
            return {
                "ok": True,
                "data": {"relation_facts": ["用户已有 Agent tool use 知识"]},
            }
        return {"ok": False, "error": "unsupported"}


class CountingGraphTools:
    def __init__(self):
        self.graph_search_calls = 0

    def __contains__(self, name: str) -> bool:
        return name == "graph_search"

    def invoke_direct(self, name: str, **kwargs):
        if name == "graph_search":
            self.graph_search_calls += 1
            return {
                "ok": True,
                "data": {
                    "relation_facts": [
                        {"note_id": "memory-layer", "fact": "Agent memory layer"}
                    ]
                },
            }
        return {"ok": False}


def _service(postgres_url):
    queue = PostgresWorkerQueueStore(postgres_url)
    store = PostgresResearchStore(postgres_url, worker_queue=queue)
    return ResearchService(store, FakeTools()), store, queue


def _execute_pipeline(service: ResearchService, **kwargs):
    run = service.prepare_run(**kwargs)
    return _execute_existing_pipeline(service, run.id, max_items=kwargs.get("max_items"))


def _execute_existing_pipeline(
    service: ResearchService,
    run_id: str,
    *,
    max_items: int | None = None,
):
    service.initialize_state(run_id)
    service.run_research_loop(run_id)
    run = service.synthesize_digest(run_id, max_items=max_items)
    service.verify_digest(run_id)
    return run


def test_research_loop_enforces_tool_call_budget(postgres_url):
    service, store, _ = _service(postgres_url)
    run = service.prepare_run(
        user_id="alice",
        topic="AI Agent",
        budget=ResearchBudget(max_queries=5, max_search_results=30, max_fulltext_fetches=5, max_tool_calls=2),
    )

    service.initialize_state(run.id)
    state = service.run_research_loop(run.id)

    assert state.tool_call_count == 2
    assert state.stop_reason == "tool budget exhausted"
    assert len(state.tool_call_traces) == 2
    assert [trace.tool_name for trace in state.tool_call_traces] == ["web_search", "capture_url"]
    assert all(trace.decision_id for trace in state.tool_call_traces)
    persisted = store.get_run(run.id)
    assert persisted.research_state.tool_call_count == 2


def test_initialize_state_understands_research_request_with_llm(postgres_url):
    service, store, _ = _service(postgres_url)

    def understand(prompt: str, name: str) -> str:
        assert name == "research_request_understanding"
        return (
            '{"topic":"Agent Runtime SDK",'
            '"instructions":"高可信优先；优先结合个人 Agent 工具调用知识",'
            '"max_items":1,'
            '"lookback_hours":168,'
            '"policy":{"research_type":"technical_product_update",'
            '"source_preference":["official","docs","github","paper","media"],'
            '"evidence_requirement":"official_or_multi_source",'
            '"ranking_objective":"confidence_first",'
            '"verification_strictness":"medium_high"},'
            '"query_plan":['
            '{"query":"Agent Runtime SDK official announcement","intent":"official","priority":0.9},'
            '{"query":"Agent Runtime SDK documentation release notes","intent":"docs","priority":0.85},'
            '{"query":"Agent Runtime SDK GitHub release","intent":"repo","priority":0.8},'
            '{"query":"Agent Runtime SDK technical report","intent":"technical","priority":0.7},'
            '{"query":"Agent Runtime SDK latest news","intent":"media","priority":0.4}'
            ']}'
        )

    service.generate_text = understand
    run = service.prepare_run(
        user_id="alice",
        topic="调研 Agent Runtime SDK 最近的重要发布，最多整理 1 条，高可信，优先和我已有 Agent 工具调用知识相关",
        max_items=5,
    )

    state = service.initialize_state(run.id)
    updated = store.get_run(run.id)

    assert state.topic == "Agent Runtime SDK"
    assert state.instructions == "高可信优先；优先结合个人 Agent 工具调用知识"
    assert state.max_items == 1
    assert state.policy.research_type == "technical_product_update"
    assert state.policy.source_preference[:3] == ["official", "docs", "github"]
    assert [query.intent for query in state.query_plan] == [
        "official",
        "docs",
        "repo",
    ]
    assert [decision.query for decision in state.decisions] == [
        "Agent Runtime SDK official announcement",
        "Agent Runtime SDK documentation release notes",
        "Agent Runtime SDK GitHub release",
    ]
    assert updated.topic == state.topic
    assert updated.instructions == state.instructions
    assert updated.max_items == 1
    assert updated.policy.research_type == "technical_product_update"
    assert [query.query for query in updated.query_plan_details] == updated.query_plan
    assert int((updated.window_end - updated.window_start).total_seconds() // 3600) == 168


def test_research_next_action_uses_llm_to_choose_gap_action(postgres_url):
    service, _, _ = _service(postgres_url)
    calls = []

    def choose_independent(prompt: str, name: str) -> str:
        calls.append((name, prompt))
        if name == "research_policy_decision":
            return '{"action": "unsupported"}'
        return '{"candidate_id": "candidate_3", "reason": "official source is already less useful than independent confirmation"}'

    service.generate_text = choose_independent
    event = ResearchEvent(
        canonical_key="agent-model",
        title="OpenAI releases Agent Model",
        summary="Release summary",
        sources=[
            ResearchSource(
                url="https://news.example/openai-agent",
                canonical_url="https://news.example/openai-agent",
                domain="news.example",
                title="OpenAI releases Agent Model",
                source_type="media",
            )
        ],
        personal_relevance=PersonalRelevance(score=0.5),
        status="uncertain",
    )
    state = ResearchState(
        run_id="run-1",
        topic="AI Agent",
        window_start=datetime(2026, 6, 23, 0, 0, tzinfo=UTC),
        window_end=datetime(2026, 6, 24, 0, 0, tzinfo=UTC),
        query_history=["AI Agent latest news"],
        decisions=[
            ResearchDecision(
                iteration=1,
                action="search_web",
                query="AI Agent latest news",
                status="executed",
            )
        ],
        evidence_gaps=[
            EvidenceGap(
                event_id=event.id,
                type="missing_primary_source",
                severity=0.6,
                status="open",
            ),
            EvidenceGap(
                event_id=event.id,
                type="single_source",
                severity=0.7,
                status="open",
            ),
        ],
        iteration_count=1,
        policy=ResearchPolicy(verification_strictness="high"),
    )

    decision = service._next_research_decision(state, [event])

    assert [call[0] for call in calls] == [
        "research_policy_decision",
        "research_next_action",
    ]
    assert decision.query == "OpenAI releases Agent Model independent coverage"
    assert decision.purpose == "find independent source"
    assert "model:" in decision.reason


def test_research_policy_can_propose_new_search_query(postgres_url):
    service, _, _ = _service(postgres_url)
    calls = []

    def choose_policy_query(prompt: str, name: str) -> str:
        calls.append((name, prompt))
        return (
            '{"action":"search_web",'
            '"query":"OpenAI Agent Model technical report primary source",'
            '"purpose":"find primary technical evidence",'
            '"expected_gain":"official_confirmation",'
            '"cost_level":"low",'
            '"reason":"a technical primary source is more useful than another generic announcement"}'
        )

    service.generate_text = choose_policy_query
    event = ResearchEvent(
        canonical_key="agent-model",
        title="OpenAI releases Agent Model",
        summary="Release summary",
        sources=[
            ResearchSource(
                url="https://news.example/openai-agent",
                canonical_url="https://news.example/openai-agent",
                domain="news.example",
                title="OpenAI releases Agent Model",
                source_type="media",
            )
        ],
        status="uncertain",
    )
    state = ResearchState(
        run_id="run-1",
        topic="AI Agent",
        window_start=datetime(2026, 6, 23, 0, 0, tzinfo=UTC),
        window_end=datetime(2026, 6, 24, 0, 0, tzinfo=UTC),
        query_history=["AI Agent latest news"],
        evidence_gaps=[
            EvidenceGap(
                event_id=event.id,
                type="missing_primary_source",
                severity=0.6,
                status="open",
            )
        ],
        iteration_count=1,
    )

    decision = service._next_research_decision(state, [event])

    assert calls[0][0] == "research_policy_decision"
    assert decision.query == "OpenAI Agent Model technical report primary source"
    assert decision.purpose == "find primary technical evidence"
    assert decision.reason.startswith("a technical primary source")


def test_research_policy_rejects_duplicate_query_and_falls_back(postgres_url):
    service, _, _ = _service(postgres_url)
    calls = []

    def duplicate_query(prompt: str, name: str) -> str:
        calls.append(name)
        return (
            '{"action":"search_web",'
            '"query":"AI Agent latest news",'
            '"purpose":"retry",'
            '"expected_gain":"recency",'
            '"cost_level":"low",'
            '"reason":"try again"}'
        )

    service.generate_text = duplicate_query
    event = ResearchEvent(
        canonical_key="agent-model",
        title="OpenAI releases Agent Model",
        summary="Release summary",
        sources=[
            ResearchSource(
                url="https://news.example/openai-agent",
                canonical_url="https://news.example/openai-agent",
                domain="news.example",
                title="OpenAI releases Agent Model",
                source_type="media",
            )
        ],
        status="uncertain",
    )
    state = ResearchState(
        run_id="run-1",
        topic="AI Agent",
        window_start=datetime(2026, 6, 23, 0, 0, tzinfo=UTC),
        window_end=datetime(2026, 6, 24, 0, 0, tzinfo=UTC),
        query_history=["AI Agent latest news"],
        evidence_gaps=[
            EvidenceGap(
                event_id=event.id,
                type="missing_primary_source",
                severity=0.6,
                status="open",
            )
        ],
        iteration_count=1,
    )

    decision = service._next_research_decision(state, [event])

    assert calls == ["research_policy_decision"]
    assert decision.query == "OpenAI releases Agent Model official announcement"
    assert decision.reason == "resolve missing_primary_source gap"


def test_research_satisfaction_llm_can_stop_loop(postgres_url):
    service, _, _ = _service(postgres_url)

    def satisfied(prompt: str, name: str) -> str:
        assert name == "research_satisfaction"
        return (
            '{"coverage_score":1.0,'
            '"confidence_score":0.95,'
            '"remaining_critical_gap_ids":[],'
            '"marginal_gain":0.05,'
            '"should_continue":false,'
            '"reason":"target is satisfied with enough verified evidence"}'
        )

    service.generate_text = satisfied
    event = ResearchEvent(
        canonical_key="agent-model",
        title="OpenAI releases Agent Model",
        summary="Release summary",
        sources=[
            ResearchSource(
                url="https://news.example/openai-agent",
                canonical_url="https://news.example/openai-agent",
                domain="news.example",
                title="OpenAI releases Agent Model",
                source_type="media",
            )
        ],
        confidence_score=0.3,
        status="uncertain",
    )
    state = ResearchState(
        run_id="run-1",
        topic="AI Agent",
        max_items=1,
        window_start=datetime(2026, 6, 23, 0, 0, tzinfo=UTC),
        window_end=datetime(2026, 6, 24, 0, 0, tzinfo=UTC),
        query_history=["AI Agent latest news"],
        iteration_count=1,
        evidence_gaps=[
            EvidenceGap(
                event_id=event.id,
                type="missing_primary_source",
                severity=0.6,
                status="open",
            )
        ],
    )

    assert service._should_stop_loop(state, [event])
    assert state.stop_reason == "target is satisfied with enough verified evidence"
    assert state.satisfaction.coverage_score == 1.0
    assert state.satisfaction.should_continue is False
    assert state.satisfaction_model_call_count == 1
    assert any(timing.stage == "llm_research_satisfaction" for timing in state.stage_timings)


def test_research_satisfaction_parses_string_false(postgres_url):
    service, _, _ = _service(postgres_url)

    def satisfied(prompt: str, name: str) -> str:
        assert name == "research_satisfaction"
        return (
            '{"coverage_score":1.0,'
            '"confidence_score":0.9,'
            '"remaining_critical_gap_ids":[],'
            '"marginal_gain":0.0,'
            '"should_continue":"false",'
            '"reason":"string false still means stop"}'
        )

    service.generate_text = satisfied
    event = ResearchEvent(
        canonical_key="agent-model",
        title="OpenAI releases Agent Model",
        summary="Release summary",
        sources=[
            ResearchSource(
                url="https://news.example/openai-agent",
                canonical_url="https://news.example/openai-agent",
                domain="news.example",
                title="OpenAI releases Agent Model",
                source_type="media",
            )
        ],
        confidence_score=0.3,
        status="uncertain",
    )
    state = ResearchState(
        run_id="run-1",
        topic="AI Agent",
        max_items=1,
        window_start=datetime(2026, 6, 23, 0, 0, tzinfo=UTC),
        window_end=datetime(2026, 6, 24, 0, 0, tzinfo=UTC),
        query_history=["AI Agent latest news"],
        iteration_count=1,
        evidence_gaps=[
            EvidenceGap(
                event_id=event.id,
                type="missing_primary_source",
                severity=0.6,
                status="open",
            )
        ],
    )

    assert service._should_stop_loop(state, [event])
    assert state.stop_reason == "string false still means stop"
    assert state.satisfaction_model_call_count == 1


def test_research_satisfaction_skips_llm_when_fallback_already_satisfied(postgres_url):
    service, _, _ = _service(postgres_url)
    calls = []
    service.generate_text = lambda prompt, name: calls.append(name) or "{}"
    event = ResearchEvent(
        canonical_key="agent-model",
        title="OpenAI releases Agent Model",
        summary="Release summary",
        sources=[
            ResearchSource(
                url="https://openai.com/news/agent",
                canonical_url="https://openai.com/news/agent",
                domain="openai.com",
                title="OpenAI releases Agent Model",
                source_type="official",
            )
        ],
        confidence_score=0.95,
        status="verified",
    )
    state = ResearchState(
        run_id="run-1",
        topic="AI Agent",
        max_items=1,
        window_start=datetime(2026, 6, 23, 0, 0, tzinfo=UTC),
        window_end=datetime(2026, 6, 24, 0, 0, tzinfo=UTC),
        query_history=["AI Agent latest news"],
        iteration_count=1,
    )

    assert service._should_stop_loop(state, [event])
    assert calls == []
    assert state.stop_reason == "research target satisfaction reached"
    assert state.satisfaction_model_call_count == 0


def test_research_next_action_falls_back_when_llm_choice_is_invalid(postgres_url):
    service, _, _ = _service(postgres_url)
    service.generate_text = lambda prompt, name: '{"candidate_id": "missing"}'
    event = ResearchEvent(
        canonical_key="agent-model",
        title="OpenAI releases Agent Model",
        summary="Release summary",
        sources=[
            ResearchSource(
                url="https://news.example/openai-agent",
                canonical_url="https://news.example/openai-agent",
                domain="news.example",
                title="OpenAI releases Agent Model",
                source_type="media",
            )
        ],
        status="uncertain",
    )
    state = ResearchState(
        run_id="run-1",
        topic="AI Agent",
        window_start=datetime(2026, 6, 23, 0, 0, tzinfo=UTC),
        window_end=datetime(2026, 6, 24, 0, 0, tzinfo=UTC),
        query_history=["AI Agent latest news"],
        evidence_gaps=[
            EvidenceGap(
                event_id=event.id,
                type="single_source",
                severity=0.7,
                status="open",
            ),
            EvidenceGap(
                event_id=event.id,
                type="missing_primary_source",
                severity=0.6,
                status="open",
            ),
        ],
        iteration_count=1,
    )

    decision = service._next_research_decision(state, [event])

    assert decision.query == "OpenAI releases Agent Model official announcement"
    assert decision.reason == "resolve missing_primary_source gap"


def test_personal_relevance_ranking_reuses_state_cache(postgres_url):
    tools = CountingGraphTools()
    service, _, _ = _service(postgres_url)
    service.tools = tools
    run = ResearchRun(
        id="run-1",
        user_id="alice",
        topic="Agent memory",
        window_start=datetime(2026, 6, 23, 0, 0, tzinfo=UTC),
        window_end=datetime(2026, 6, 24, 0, 0, tzinfo=UTC),
    )
    event = ResearchEvent(
        canonical_key="agent-memory",
        title="Agent memory adapter design improves recall",
        summary="A design note about agent memory adapters.",
        entities=["Agent memory"],
        sources=[
            ResearchSource(
                id="source-1",
                decision_id="decision-1",
                url="https://engineering.example/agent-memory-adapter",
                canonical_url="https://engineering.example/agent-memory-adapter",
                domain="engineering.example",
                title="Agent memory adapter design improves recall",
                source_type="blog",
            )
        ],
    )
    state = ResearchState(
        run_id=run.id,
        topic=run.topic,
        window_start=run.window_start,
        window_end=run.window_end,
    )

    first = service._personalize_and_rank(run, None, [event], state)
    second = service._personalize_and_rank(run, None, [event.model_copy(deep=True)], state)

    assert tools.graph_search_calls == 1
    assert len(state.personal_relevance_cache) == 1
    assert first[0].personal_relevance.score == second[0].personal_relevance.score


def test_research_pipeline_persists_events_and_digest(postgres_url):
    service, store, _ = _service(postgres_url)

    run = _execute_pipeline(
        service,
        user_id="alice",
        topic="AI Agent",
        instructions="只看重要技术发布",
        max_items=3,
    )

    assert run.status == "completed_with_limitations"
    assert run.source_count == 2
    assert run.event_count == 1
    digest = store.get_digest(run.digest_id)
    assert digest is not None
    assert len(digest.items) == 1
    assert digest.items[0].confidence_label == "已验证"
    assert digest.items[0].personal_relevance
    persisted = store.get_run(run.id)
    assert persisted.research_state is not None
    executed_decisions = [
        decision for decision in persisted.research_state.decisions
        if decision.status == "executed" and decision.action == "search_web"
    ]
    assert executed_decisions
    assert all(decision.started_at is not None for decision in executed_decisions)
    assert all(decision.completed_at is not None for decision in executed_decisions)
    decision_ids = {decision.id for decision in executed_decisions}
    timing_stages = {timing.stage for timing in persisted.research_state.stage_timings}
    assert "execute_research_decision" in timing_stages
    assert "personalize_and_rank" in timing_stages
    tool_names = [trace.tool_name for trace in persisted.research_state.tool_call_traces]
    assert "web_search" in tool_names
    assert "capture_url" in tool_names
    assert "graph_search" in tool_names
    sources = store.list_run_sources(run.id)
    assert {source.decision_id for source in sources} == {executed_decisions[0].id}
    assert all(source.query == executed_decisions[0].query for source in sources)
    events = store.list_run_events(run.id)
    assert events[0].source_ids == [source.id for source in sources]
    assert events[0].frame is not None
    assert events[0].frame.actor or events[0].frame.object
    assert digest.items[0].source_ids == events[0].source_ids
    assert set(digest.items[0].decision_ids).issubset(decision_ids)
    assert digest.items[0].claims[0].event_id == events[0].id
    assert digest.items[0].claims[0].source_ids
    assert set(digest.items[0].claims[0].decision_ids).issubset(decision_ids)


def test_subscription_run_is_durable_and_idempotent(postgres_url):
    service, store, queue = _service(postgres_url)
    subscription = store.upsert_subscription(ResearchSubscription(
        user_id="alice",
        name="AI 日报",
        topic="AI",
        delivery=DeliveryTarget(target_id="chat-1"),
    ))
    end = datetime(2026, 6, 23, 1, 0, tzinfo=UTC)

    first = service.enqueue_subscription_run(subscription, window_end=end)
    second = service.enqueue_subscription_run(subscription, window_end=end)

    assert first.id == second.id
    tasks = queue.list_tasks(queue="research")
    assert len(tasks) == 1
    assert tasks[0].payload["run_id"] == first.id


def test_scheduler_respects_timezone_and_last_window(postgres_url):
    service, store, _ = _service(postgres_url)
    subscription = store.upsert_subscription(ResearchSubscription(
        user_id="alice",
        name="AI 日报",
        topic="AI",
        schedule=SchedulePolicy(schedule_time="09:00", timezone="Asia/Shanghai"),
    ))
    now = datetime(2026, 6, 23, 1, 5, tzinfo=UTC)

    assert subscription_due(subscription, now)
    runs = ResearchScheduler(store, service).enqueue_due(now)
    assert len(runs) == 1

    completed = subscription.model_copy(update={"last_window_end": now})
    store.upsert_subscription(completed)
    assert not subscription_due(completed, now)
    assert ResearchScheduler(store, service).enqueue_due(now) == []


def test_research_feedback_is_persisted(postgres_url):
    service, store, _ = _service(postgres_url)
    run = _execute_pipeline(service, user_id="alice", topic="AI")
    digest = store.get_digest(run.digest_id)
    event_id = digest.items[0].event_id

    feedback = service.feedback(ResearchFeedback(
        user_id="alice",
        run_id=run.id,
        event_id=event_id,
        action="useful",
    ))

    assert feedback.action == "useful"


def test_feedback_updates_subscription_preferences(postgres_url):
    service, store, _ = _service(postgres_url)
    subscription = store.upsert_subscription(ResearchSubscription(
        user_id="alice",
        name="AI 日报",
        topic="AI",
    ))
    run = service.enqueue_subscription_run(
        subscription,
        window_end=datetime(2026, 6, 23, 1, 0, tzinfo=UTC),
    )
    completed = _execute_existing_pipeline(service, run.id)
    digest = store.get_digest(completed.digest_id)

    service.feedback(ResearchFeedback(
        user_id="alice",
        subscription_id=subscription.id,
        run_id=run.id,
        event_id=digest.items[0].event_id,
        action="not_interested",
    ))

    updated = store.get_subscription(subscription.id)
    assert "AI" in updated.content_preferences.exclude_topics


def test_worker_separates_research_and_delivery_tasks(postgres_url):
    service, store, queue = _service(postgres_url)
    subscription = store.upsert_subscription(ResearchSubscription(
        user_id="alice",
        name="AI 日报",
        topic="AI",
        delivery=DeliveryTarget(target_id="chat-1"),
    ))
    run = service.enqueue_subscription_run(
        subscription,
        window_end=datetime(2026, 6, 23, 1, 0, tzinfo=UTC),
    )

    class Router:
        sent = []

        def send(self, target, message):
            from personal_agent.application.review.models import DeliveryResult
            self.sent.append((target, message))
            return DeliveryResult(ok=True, provider_message_id="m1")

    router = Router()
    service.set_delivery_router(router)
    def execute_entry(entry_input):
        _execute_existing_pipeline(service, entry_input.metadata["research_run_id"])
        return SimpleNamespace(run_status="completed")

    runtime = SimpleNamespace(
        research_service=service,
        research_store=store,
        worker_queue_store=queue,
        execute_entry=execute_entry,
    )
    worker = WorkflowWorker(runtime, queue="research", worker_id="research-test")

    first = worker.run_once()
    second = worker.run_once()

    assert first.completed == 1
    assert second.completed == 1
    assert len(router.sent) == 1
    assert store.get_run(run.id).status == "completed_verified"


def test_subscription_parser_workflow_intents_are_registered():
    from personal_agent.planning.workflow import WORKFLOW_REGISTRY

    research_steps = WORKFLOW_REGISTRY.select("research_once").steps
    assert [step.tool_name for step in research_steps[:5]] == [
        "research_prepare_run",
        "research_initialize_state",
        "research_run_loop",
        "research_synthesize_digest",
        "research_verify_digest",
    ]
    assert (
        WORKFLOW_REGISTRY.select("create_research_subscription").steps[0].tool_name
        == "create_research_subscription"
    )


def test_research_workflow_contracts_are_deterministic_unit_contracts():
    from personal_agent.planning.workflow import WORKFLOW_REGISTRY

    research_once = WORKFLOW_REGISTRY.select("research_once")
    assert [(step.step_id, step.tool_name, step.depends_on) for step in research_once.steps] == [
        ("research-prepare", "research_prepare_run", ()),
        ("research-initialize", "research_initialize_state", ("research-prepare",)),
        ("research-loop", "research_run_loop", ("research-initialize",)),
        ("research-synthesize", "research_synthesize_digest", ("research-loop",)),
        ("research-verify", "research_verify_digest", ("research-synthesize",)),
        ("research-compose", None, ("research-verify",)),
    ]
    assert research_once.steps[2].side_effects == ("external_network", "write_longterm")

    execute_run = WORKFLOW_REGISTRY.select("execute_research_run")
    assert [(step.step_id, step.tool_name, step.depends_on) for step in execute_run.steps] == [
        ("research-initialize", "research_initialize_state", ()),
        ("research-loop", "research_run_loop", ("research-initialize",)),
        ("research-synthesize", "research_synthesize_digest", ("research-loop",)),
        ("research-verify", "research_verify_digest", ("research-synthesize",)),
    ]

    manage = WORKFLOW_REGISTRY.select("manage_research")
    assert manage.steps[0].allowed_tools == (
        "list_research_subscriptions",
        "update_research_subscription",
        "pause_research_subscription",
        "resume_research_subscription",
        "run_research_subscription_now",
        "list_research_runs",
        "get_research_digest",
        "submit_research_feedback",
        "save_research_event",
    )


def test_feishu_research_feedback_parser():
    from personal_agent.adapters.feishu.service import _parse_research_feedback

    assert _parse_research_feedback("N2 不感兴趣") == ("N2", "not_interested")
    assert _parse_research_feedback("n1 入库") == ("N1", "save")
    assert _parse_research_feedback("R1 记得") is None
