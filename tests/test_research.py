from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from personal_agent.research import (
    DeliveryTarget,
    ResearchFeedback,
    ResearchScheduler,
    ResearchService,
    ResearchSubscription,
    SchedulePolicy,
    subscription_due,
)
from personal_agent.storage.postgres_research_store import PostgresResearchStore
from personal_agent.storage.postgres_worker_queue_store import PostgresWorkerQueueStore
from personal_agent.agent.worker import WorkflowWorker

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
    service.plan_queries(run_id)
    service.collect_sources(run_id)
    service.cluster_events(run_id)
    service.rank_events(run_id, max_items=max_items)
    return service.compose_digest(run_id, max_items=max_items)


def test_research_pipeline_persists_events_and_digest(postgres_url):
    service, store, _ = _service(postgres_url)

    run = _execute_pipeline(
        service,
        user_id="alice",
        topic="AI Agent",
        instructions="只看重要技术发布",
        max_items=3,
    )

    assert run.status == "completed"
    assert run.source_count == 2
    assert run.event_count == 1
    digest = store.get_digest(run.digest_id)
    assert digest is not None
    assert len(digest.items) == 1
    assert digest.items[0].confidence_label == "已验证"
    assert digest.items[0].personal_relevance


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
            from personal_agent.review.models import DeliveryResult
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
    assert store.get_run(run.id).status == "completed"


def test_subscription_parser_workflow_intents_are_registered():
    from personal_agent.agent.workflow import WORKFLOW_REGISTRY

    research_steps = WORKFLOW_REGISTRY.select("research_once").steps
    assert [step.tool_name for step in research_steps[:6]] == [
        "research_prepare_run",
        "research_plan_queries",
        "research_collect_sources",
        "research_cluster_events",
        "research_rank_events",
        "research_compose_digest",
    ]
    assert (
        WORKFLOW_REGISTRY.select("create_research_subscription").steps[0].tool_name
        == "create_research_subscription"
    )


def test_feishu_research_feedback_parser():
    from personal_agent.feishu.service import _parse_research_feedback

    assert _parse_research_feedback("N2 不感兴趣") == ("N2", "not_interested")
    assert _parse_research_feedback("n1 入库") == ("N1", "save")
    assert _parse_research_feedback("R1 记得") is None
