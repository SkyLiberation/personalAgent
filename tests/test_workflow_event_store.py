from __future__ import annotations

from personal_agent.agent.orchestration_models import AgentEvent
from personal_agent.agent.runtime import AgentRuntime
from personal_agent.core.models import EntryInput
from personal_agent.graphiti.store import GraphitiStore
from personal_agent.storage.postgres_memory_store import PostgresMemoryStore
from personal_agent.storage.postgres_workflow_event_store import PostgresWorkflowEventStore
from tests.conftest import stub_router_decision


def test_workflow_event_store_records_events_once(postgres_url, clean_postgres_business_tables):
    store = PostgresWorkflowEventStore(postgres_url)
    events = [
        AgentEvent(
            event_id="event-1",
            run_id="run-1",
            thread_id="u:s",
            type="entry_started",
            payload={"text_preview": "hello"},
        ),
        AgentEvent(
            event_id="event-2",
            run_id="run-1",
            thread_id="u:s",
            type="run_completed",
            payload={"answer": "ok"},
        ),
    ]

    assert store.record_agent_events(events) == 2
    assert store.record_agent_events(events) == 0

    restored = store.list_events("run-1")
    assert [event.event_id for event in restored] == ["event-1", "event-2"]
    assert restored[0].payload == {"text_preview": "hello"}


def test_execute_entry_persists_workflow_events(settings, temp_dir, clean_postgres_business_tables, monkeypatch):
    runtime = AgentRuntime(
        settings,
        store=PostgresMemoryStore(temp_dir, settings.postgres_url),
        graph_store=GraphitiStore(settings),
    )
    monkeypatch.setattr(runtime.intent_router, "_classify_with_llm", stub_router_decision)

    result = runtime.execute_entry(
        EntryInput(text="你好", user_id="event-user", session_id="event-session")
    )

    events = runtime.workflow_event_store.list_events(result.run_id)

    assert [event["type"] for event in result.events] == [event.type for event in events]
    assert events[0].type == "entry_started"
    assert events[-1].type == "run_completed"
