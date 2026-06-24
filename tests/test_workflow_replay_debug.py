from __future__ import annotations

from dataclasses import replace

import pytest

from personal_agent.agent.workflow import WORKFLOW_REGISTRY
from personal_agent.kernel.models import EntryInput
from tests.conftest import stub_router_decision


@pytest.fixture
def runtime(settings, clean_postgres_business_tables):
    from personal_agent.agent.runtime import AgentRuntime
    from personal_agent.graphiti.store import GraphitiStore
    from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore

    runtime = AgentRuntime(
        settings=settings,
        store=PostgresMemoryStore(settings.data_dir, settings.postgres_url),
        graph_store=GraphitiStore(settings),
    )
    runtime._intent_router._classify_with_llm = stub_router_decision
    return runtime


def _first_checkpoint_id(runtime, run_id: str) -> str:
    history = runtime.list_run_history(run_id, limit=20)
    return next(item["checkpoint_id"] for item in history if item.get("checkpoint_id"))


def test_debug_bundle_includes_events_history_and_replays(runtime):
    result = runtime.execute_entry(
        EntryInput(text="你好", user_id="test-user", session_id="debug-bundle")
    )
    checkpoint_id = _first_checkpoint_id(runtime, result.run_id or "")

    replayed = runtime.replay_from_checkpoint(
        thread_id=result.thread_id or "",
        checkpoint_id=checkpoint_id,
        updates={},
    )
    bundle = runtime.build_workflow_debug_bundle(result.run_id or "")

    assert replayed.run_id == result.run_id
    assert bundle["run_id"] == result.run_id
    assert bundle["events"]
    assert bundle["history"]
    assert bundle["replays"]
    assert bundle["replays"][0]["status"] == "completed"


def test_fork_from_checkpoint_creates_new_run_and_records_event(runtime):
    result = runtime.execute_entry(
        EntryInput(text="你好", user_id="test-user", session_id="fork-debug")
    )
    checkpoint_id = _first_checkpoint_id(runtime, result.run_id or "")

    forked = runtime.fork_from_checkpoint(
        thread_id=result.thread_id or "",
        checkpoint_id=checkpoint_id,
        updates={},
    )
    replay_runs = runtime.list_replay_runs(result.run_id or "")
    event_types = [event.get("type") for event in forked.events if isinstance(event, dict)]

    assert forked.run_id
    assert forked.run_id != result.run_id
    assert replay_runs
    assert "workflow_forked" in event_types


def test_step_execution_persists_input_and_output_artifacts(runtime):
    result = runtime.execute_entry(
        EntryInput(text="你好", user_id="test-user", session_id="step-artifacts")
    )
    artifacts = runtime.list_workflow_artifacts(result.run_id or "", limit=20)
    snapshot = runtime.get_run_snapshot(result.run_id or "")

    kinds = {artifact.kind for artifact in artifacts}
    assert "step_input" in kinds
    assert "step_output" in kinds
    assert snapshot is not None
    assert snapshot.workflow_id == "direct_answer"
    assert snapshot.workflow_version == "v1"
    assert snapshot.steps[0]["input_artifact_id"]
    assert snapshot.steps[0]["output_artifact_id"]


def test_debug_bundle_contains_event_sourced_projection(runtime):
    result = runtime.execute_entry(
        EntryInput(text="你好", user_id="test-user", session_id="event-projection")
    )

    projection = runtime.rebuild_workflow_projection(result.run_id or "")
    bundle = runtime.build_workflow_debug_bundle(result.run_id or "")

    assert projection.status == "completed"
    assert projection.workflow_id == "direct_answer"
    assert projection.steps[0]["status"] == "completed"
    assert bundle["projection"]["workflow_id"] == "direct_answer"


def test_artifact_redaction_and_retention(runtime):
    record = runtime.workflow_replay_store.put_artifact(
        artifact_id="retention-artifact",
        run_id="retention-run",
        kind="test",
        payload={"answer": "secret", "nested": {"content": "private"}, "safe": "ok"},
    )

    redacted = runtime.redact_workflow_artifact(record.artifact_id)

    assert redacted is not None
    assert redacted.redacted_at is not None
    assert redacted.payload["answer"] == "[REDACTED]"
    assert redacted.payload["nested"]["content"] == "[REDACTED]"
    assert redacted.payload["safe"] == "ok"

    runtime.workflow_replay_store.put_artifact(
        artifact_id="expired-artifact",
        run_id="retention-run",
        kind="test",
        payload={"safe": "delete"},
        retention_days=0,
    )
    assert runtime.purge_expired_workflow_artifacts() >= 1
    assert runtime.get_workflow_artifact("expired-artifact") is None


def test_fork_from_step_reexecutes_from_selected_step(runtime):
    result = runtime.execute_entry(
        EntryInput(text="你好", user_id="test-user", session_id="fork-step")
    )
    step_id = result.steps[0]["step_id"]

    forked = runtime.fork_from_step(
        run_id=result.run_id or "",
        step_id=step_id,
    )

    assert forked.run_id
    assert forked.run_id != result.run_id
    assert forked.steps[0]["status"] == "completed"
    assert any(
        event.get("type") == "workflow_forked"
        and event.get("payload", {}).get("source_step_id") == step_id
        for event in forked.events
        if isinstance(event, dict)
    )


def test_state_migration_registration_and_preview(runtime):
    result = runtime.execute_entry(
        EntryInput(text="你好", user_id="test-user", session_id="migration-preview")
    )
    source_spec = WORKFLOW_REGISTRY.select("direct_answer")
    runtime.workflow_definition_store.record_definitions(
        [replace(source_spec, version="v2")]
    )
    runtime.set_workflow_state_migration(
        source_spec.workflow_id,
        from_version=source_spec.version,
        to_version="v2",
        step_mapping={"direct-compose": "direct-compose"},
    )

    migrated = runtime.preview_workflow_state_migration(
        run_id=result.run_id or "",
        to_version="v2",
    )

    assert migrated.steps[0].workflow_version == "v2"
    assert migrated.steps[0].status == "completed"
    assert "direct-compose" in migrated.results
