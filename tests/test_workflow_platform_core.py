from __future__ import annotations

from personal_agent.agent.orchestration_models import AgentEvent, StepExecutionState, StepRunState
from personal_agent.planning.workflow import WorkflowSpec, WorkflowStepSpec
from personal_agent.agent.workflow_event_projection import project_workflow_events
from personal_agent.agent.workflow_state_migration import (
    migrate_step_execution,
    reset_step_and_dependents,
)


def test_event_projection_rebuilds_step_artifacts_and_terminal_state():
    events = [
        AgentEvent(
            run_id="run-1",
            thread_id="thread-1",
            type="intent_classified",
            payload={"intent": "ask"},
        ),
        AgentEvent(
            run_id="run-1",
            thread_id="thread-1",
            type="steps_projected",
            payload={
                "workflow_id": "ask",
                "workflow_version": "v2",
                "steps": [{"step_id": "retrieve", "status": "planned"}],
            },
        ),
        AgentEvent(
            run_id="run-1",
            thread_id="thread-1",
            type="step_started",
            payload={"step_id": "retrieve"},
        ),
        AgentEvent(
            run_id="run-1",
            thread_id="thread-1",
            type="artifact_written",
            payload={
                "step_id": "retrieve",
                "kind": "step_output",
                "artifact_id": "artifact-1",
            },
        ),
        AgentEvent(
            run_id="run-1",
            thread_id="thread-1",
            type="step_completed",
            payload={"step_id": "retrieve", "result_summary": "3 matches"},
        ),
        AgentEvent(
            run_id="run-1",
            thread_id="thread-1",
            type="run_completed",
            payload={"answer": "done"},
        ),
    ]

    projection = project_workflow_events("run-1", events)

    assert projection.status == "completed"
    assert projection.intent == "ask"
    assert projection.workflow_version == "v2"
    assert projection.steps[0]["status"] == "completed"
    assert projection.steps[0]["output_artifact_id"] == "artifact-1"
    assert projection.answer == "done"


def test_reset_step_resets_transitive_dependents_only():
    state = StepExecutionState(
        steps=[
            StepRunState(step_id="a", status="completed"),
            StepRunState(step_id="b", depends_on=["a"], status="completed"),
            StepRunState(step_id="c", depends_on=["b"], status="completed"),
            StepRunState(step_id="independent", status="completed"),
        ],
        results={"a": 1, "b": 2, "c": 3, "independent": 4},
    )

    reset = reset_step_and_dependents(state, "b")

    assert [step.status for step in reset.steps] == [
        "completed",
        "planned",
        "planned",
        "completed",
    ]
    assert reset.results == {"a": 1, "independent": 4}
    assert reset.current_step_index == 1


def test_state_migration_reuses_completed_mapped_steps():
    source = StepExecutionState(
        steps=[
            StepRunState(
                step_id="old_retrieve",
                status="completed",
                output_artifact_id="artifact-old",
            ),
            StepRunState(step_id="old_answer", status="completed"),
        ],
        results={"old_retrieve": {"matches": 2}, "old_answer": "answer"},
    )
    target = WorkflowSpec(
        workflow_id="ask",
        version="v2",
        intent="ask",
        projection_policy="step_projection",
        steps=(
            WorkflowStepSpec(
                step_id="retrieve",
                action_type="retrieve",
                description="retrieve",
            ),
            WorkflowStepSpec(
                step_id="rerank",
                action_type="resolve",
                description="rerank",
                depends_on=("retrieve",),
            ),
        ),
    )

    migrated = migrate_step_execution(
        source,
        target,
        step_mapping={"retrieve": "old_retrieve"},
    )

    assert migrated.steps[0].status == "completed"
    assert migrated.steps[0].output_artifact_id == "artifact-old"
    assert migrated.steps[1].status == "planned"
    assert migrated.results == {"retrieve": {"matches": 2}}
    assert migrated.current_step_index == 1
