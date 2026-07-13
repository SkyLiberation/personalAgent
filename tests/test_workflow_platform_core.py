from __future__ import annotations

from personal_agent.orchestration.orchestration_models import AgentEvent
from personal_agent.orchestration.workflow_event_projection import project_workflow_events


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
