from personal_agent.kernel.contracts.events import AgentEvent
from personal_agent.orchestration.execution_event_projection import project_execution_events


def test_open_execution_has_no_fake_procedure_identity() -> None:
    projection = project_execution_events("run", [
        AgentEvent(
            run_id="run",
            thread_id="thread",
            type="task_analyzed",
            payload={"result_contracts": ["response"]},
        ),
        AgentEvent(
            run_id="run",
            thread_id="thread",
            type="action_materialized",
            payload={"action": {"meta_capability": "acquire"}},
        ),
    ])

    assert projection.result_contract == "response"
    assert projection.procedure_id == ""


def test_procedure_identity_appears_only_after_procedure_started() -> None:
    projection = project_execution_events("run", [AgentEvent(
        run_id="run",
        thread_id="thread",
        type="procedure_started",
        payload={"procedure_invocation": {
            "procedure_id": "knowledge_ingest",
            "procedure_version": "1",
        }},
    )])

    assert projection.procedure_id == "knowledge_ingest"
    assert projection.procedure_version == "1"
