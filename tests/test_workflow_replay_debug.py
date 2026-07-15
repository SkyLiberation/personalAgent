from __future__ import annotations

import pytest

from personal_agent.kernel.models import EntryInput
from tests.conftest import stub_task_analysis


@pytest.fixture
def runtime(settings, clean_postgres_business_tables):
    from personal_agent.orchestration.runtime import AgentRuntime
    from personal_agent.memory.graphiti.store import GraphitiStore
    from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore

    runtime = AgentRuntime(
        settings=settings,
        store=PostgresMemoryStore(settings.data_dir, settings.postgres_url),
        graph_store=GraphitiStore(settings),
    )
    runtime._task_analyzer._analyze_with_model = stub_task_analysis
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
    bundle = runtime.build_execution_debug_bundle(result.run_id or "")

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
    event_types = [
        event.get("type") for event in forked.events if isinstance(event, dict)
    ]

    assert forked.run_id
    assert forked.run_id != result.run_id
    assert replay_runs
    assert "execution_forked" in event_types


def test_step_execution_persists_input_and_output_artifacts(runtime):
    result = runtime.execute_entry(
        EntryInput(text="你好", user_id="test-user", session_id="step-artifacts")
    )
    artifacts = runtime.list_execution_artifacts(result.run_id or "", limit=20)
    snapshot = runtime.get_run_snapshot(result.run_id or "")

    kinds = {artifact.kind for artifact in artifacts}
    assert "step_input" in kinds
    assert "step_output" in kinds
    assert all(artifact.step_id for artifact in artifacts)
    assert all(artifact.schema_version >= 1 for artifact in artifacts)
    assert all(artifact.created_by_step == artifact.step_id for artifact in artifacts)
    assert all(artifact.user_id == "test-user" for artifact in artifacts)
    assert snapshot is not None
    assert snapshot.status == "completed"
    projection = runtime.rebuild_execution_projection(result.run_id or "")
    assert projection.procedure_id == ""
    assert any(step.get("input_artifact_id") for step in projection.steps)
    assert any(step.get("output_artifact_id") for step in projection.steps)


def test_step_artifacts_can_be_filtered_by_step_id(runtime):
    result = runtime.execute_entry(
        EntryInput(text="你好", user_id="test-user", session_id="step-artifact-filter")
    )
    all_artifacts = runtime.list_execution_artifacts(result.run_id or "", limit=20)
    step_id = all_artifacts[0].step_id

    artifacts = runtime.list_execution_artifacts(
        result.run_id or "",
        step_id=step_id,
        limit=20,
    )

    assert artifacts
    assert {artifact.step_id for artifact in artifacts} == {step_id}


def test_debug_bundle_contains_event_sourced_projection(runtime):
    result = runtime.execute_entry(
        EntryInput(text="你好", user_id="test-user", session_id="event-projection")
    )

    projection = runtime.rebuild_execution_projection(result.run_id or "")
    bundle = runtime.build_execution_debug_bundle(result.run_id or "")

    assert projection.status == "completed"
    assert projection.procedure_id == ""
    assert projection.steps[0]["status"] == "completed"
    assert bundle["projection"]["procedure_id"] == ""


def test_artifact_redaction_and_retention(runtime):
    record = runtime.execution_replay_store.put_artifact(
        artifact_id="retention-artifact",
        run_id="retention-run",
        step_id="retention-step",
        kind="test",
        schema_version=1,
        payload={"answer": "secret", "nested": {"content": "private"}, "safe": "ok"},
        summary="retention test",
        created_by_step="retention-step",
        user_id="test-user",
    )

    redacted = runtime.redact_execution_artifact(record.artifact_id)

    assert redacted is not None
    assert redacted.redacted_at is not None
    assert redacted.payload["answer"] == "[REDACTED]"
    assert redacted.payload["nested"]["content"] == "[REDACTED]"
    assert redacted.payload["safe"] == "ok"

    runtime.execution_replay_store.put_artifact(
        artifact_id="expired-artifact",
        run_id="retention-run",
        step_id="retention-step",
        kind="test",
        payload={"safe": "delete"},
        created_by_step="retention-step",
        user_id="test-user",
        retention_days=0,
    )
    assert runtime.purge_expired_execution_artifacts() >= 1
    assert runtime.get_execution_artifact("expired-artifact") is None
