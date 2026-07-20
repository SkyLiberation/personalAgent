"""Live end-to-end proofs for user outcomes through the production runtime.

The suite starts with raw ``EntryInput`` and uses the model/provider settings
loaded by ``Settings.from_env``.  It must not replace Task Analysis, planning,
stores, gateways, or verification with deterministic doubles.
"""

from __future__ import annotations

import json
import os
import socket
from uuid import uuid4

import pytest

from personal_agent.kernel.config import Settings
from personal_agent.kernel.llm_telemetry import collect_llm_usage
from personal_agent.kernel.models import EntryInput
from personal_agent.kernel.prompts import get_prompt
from personal_agent.orchestration.service import AgentService
from evals.e2e_quality.trace_archive import TraceArchive
from tests.conftest import POSTGRES_URL


pytestmark = pytest.mark.integration


def _live_e2e_required() -> bool:
    return os.getenv("PERSONAL_AGENT_REQUIRE_LIVE_E2E", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@pytest.fixture
def postgres_available() -> None:
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=0.5):
            pass
    except OSError:
        message = "live core E2E requires Postgres on 127.0.0.1:5432"
        if _live_e2e_required():
            pytest.fail(message)
        pytest.skip(message)


@pytest.fixture
def core_database(postgres_available, clean_postgres_business_tables) -> None:
    """Fail fast before the shared schema/reset fixture attempts a DB connection."""


@pytest.fixture
def service(temp_dir, core_database, trace_archive: TraceArchive) -> AgentService:
    settings = Settings.from_env()
    if not (
        settings.structured.api_key
        and settings.structured.base_url
        and settings.structured.model
    ):
        message = (
            "live core E2E requires STRUCTURED_* (or ROUTER_*/OPENAI_*) "
            "model configuration"
        )
        if _live_e2e_required():
            pytest.fail(message)
        pytest.skip(message)

    # Real providers are retained, while persistence and graph namespaces are
    # isolated so a live E2E run cannot write into the application's business data.
    settings = settings.model_copy(update={
        "data_dir": temp_dir,
        "postgres_url": POSTGRES_URL,
        "graphiti": settings.graphiti.model_copy(update={
            "group_prefix": f"{settings.graphiti.group_prefix}-live-e2e-{uuid4().hex}",
        }),
    })
    live_service = AgentService(settings)
    assert live_service.runtime._structured_client is not None
    trace_archive.update_environment({
        "structured_model": settings.structured.model,
        "task_analyzer_prompt_version": get_prompt("task_analyzer.system").version,
        "providers": {
            "structured_model": True,
            "openai_chat": bool(settings.openai.api_key and settings.openai.base_url),
            "graphiti": live_service.graph_store.configured(),
            "ms_graphrag": settings.ms_graphrag.enabled,
            "web_search": bool(settings.web_search.api_key),
        },
    })
    return live_service


def _run_state(service: AgentService, run_id: str):
    state = service.runtime._entry.get_run_state(run_id)
    assert state is not None, "the production checkpoint must retain the full run state"
    return state


def _execution_event_types(state) -> list[str]:
    return [event.event_type for event in state.execution_events]


def _agent_event_types(state) -> list[str]:
    return [event.type for event in state.events]


def _emit_trace(
    case_id: str,
    result,
    state,
    *,
    service: AgentService,
    llm_call_count: int,
    trace_archive: TraceArchive,
    nodeid: str,
) -> None:
    """Keep the real input/output/canonical trace in pytest failure artifacts."""
    trace = {
        "case_id": case_id,
        "input": state.entry_input.model_dump(mode="json") if state.entry_input else None,
        "llm_call_count": llm_call_count,
        "task_analysis": (
            {
                "attempts": [
                    item.model_dump(mode="json") for item in state.task_analysis_attempts
                ],
                "accepted": (
                    state.accepted_task_analysis.model_dump(mode="json")
                    if state.accepted_task_analysis else None
                ),
            }
        ),
        "task_contract": (
            state.task_contract.model_dump(mode="json") if state.task_contract else None
        ),
        "task_runtime": (
            state.task_runtime.model_dump(mode="json") if state.task_runtime else None
        ),
        "agent_events": [event.model_dump(mode="json") for event in state.events],
        "decision_audit": [
            record.model_dump(mode="json") for record in state.decision_audit
        ],
        "decision_feedback": [
            feedback.model_dump(mode="json") for feedback in state.decision_feedback
        ],
        "control_chain": {
            "proposal": (
                state.control.proposal.model_dump(mode="json")
                if state.control.proposal else None
            ),
            "admission": (
                state.decision_admission.model_dump(mode="json")
                if state.decision_admission else None
            ),
            "accepted_intent": (
                state.control.accepted_intent.model_dump(mode="json")
                if state.control.accepted_intent else None
            ),
            "resolved_command": (
                state.control.resolved_command.model_dump(mode="json")
                if state.control.resolved_command else None
            ),
        },
        "persisted_commands": [
            command.model_dump(mode="json")
            for command in service.runtime.control_plane_store.list_commands(result.run_id or "")
        ],
        "execution_events": [
            event.model_dump(mode="json") for event in state.execution_events
        ],
        "canonical_domain_events": [
            event.model_dump(mode="json")
            for event in service.runtime.control_plane_store.list_domain_events(result.run_id or "")
        ],
        "execution_grants": {
            grant_id: grant.model_dump(mode="json")
            for grant_id, grant in state.execution_grants.items()
        },
        "invocation_journal": state.invocation_journal.model_dump(mode="json"),
        "execution_fact_reports": {
            command_ref: report.model_dump(mode="json")
            for command_ref, report in state.execution_fact_reports.items()
        },
        "verification_reports": {
            goal_id: report.model_dump(mode="json")
            for goal_id, report in state.verification_reports.items()
        },
        "completion_report": (
            state.completion_report.model_dump(mode="json")
            if state.completion_report
            else None
        ),
        "verification_feedback": {
            goal_id: feedback.model_dump(mode="json")
            for goal_id, feedback in state.verification_feedback.items()
        },
        "final_answer": {
            "proposal": (
                state.final_answer_proposal.model_dump(mode="json")
                if state.final_answer_proposal else None
            ),
            "admission": (
                state.final_answer_admission.model_dump(mode="json")
                if state.final_answer_admission else None
            ),
        },
        "output": {
            "run_status": result.run_status,
            "reply_text": result.reply_text,
            "pending_confirmation": result.pending_confirmation,
        },
    }
    path = trace_archive.write_trace(nodeid=nodeid, case_id=case_id, trace=trace)
    print("LIVE_E2E_TRACE=" + json.dumps(trace, ensure_ascii=False, default=str))
    print(f"LIVE_E2E_TRACE_FILE={path}")


def test_simple_request_is_understood_answered_and_verified_live(
    service: AgentService,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    entry = EntryInput(
        text="请用一句话解释什么是递归，不需要检索或引用资料。",
        user_id="live-e2e-simple-user",
        session_id=f"live-e2e-simple-{uuid4().hex}",
        source_platform="live_e2e",
    )

    with collect_llm_usage() as usage:
        result = service.execute_entry(entry)
    state = _run_state(service, result.run_id or "")
    _emit_trace(
        "simple_response",
        result,
        state,
        service=service,
        llm_call_count=usage.call_count,
        trace_archive=trace_archive,
        nodeid=request.node.nodeid,
    )

    assert usage.call_count >= 1, "the E2E must call the configured live model"
    assert state.accepted_task_analysis is not None
    analysis = state.accepted_task_analysis.analysis
    assert analysis.outcome == "ready"
    assert len(analysis.goals) == 1
    assert analysis.goals[0].result_contract == "response"
    assert analysis.goals[0].side_effect_intent == "none"
    assert analysis.goals[0].resource_hints == []
    assert "task_analyzed" in _agent_event_types(state)

    assert result.run_status == "completed"
    assert result.reply_text.strip()
    assert state.task_contract is not None
    assert state.task_runtime is not None
    assert state.task_contract.result_contract == "response"
    assert state.task_runtime.lifecycle == "completed"
    assert state.task_runtime.goal_states["goal_1"].status == "verified"
    assert state.verification_reports["goal_1"].status == "passed"
    assert state.completion_report is not None
    assert state.completion_report.status == "complete"
    assert state.final_answer_proposal is not None
    assert state.final_answer_admission is not None
    assert state.final_answer_admission.verdict == "accepted"
    assert state.decision_audit
    assert all(record.admission.proposal_ref == record.proposal.proposal_id for record in state.decision_audit)
    assert state.completion_report.verified_goal_ids == ("goal_1",)
    assert state.execution_grants == {}
    assert "goal_verified" in _execution_event_types(state)
    assert _execution_event_types(state)[-1] == "task_completed"


def test_compound_write_then_answer_runs_from_live_understanding(
    service: AgentService,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    release_fact = "Gamma-Live-E2E-7319 的发布窗口是周五 20:00"
    user_id = "live-e2e-compound-user"
    entry = EntryInput(
        text=f"先把“{release_fact}”记入知识库，然后基于刚写入的内容回答它什么时候发布。",
        user_id=user_id,
        session_id=f"live-e2e-compound-{uuid4().hex}",
        source_platform="live_e2e",
    )

    with collect_llm_usage() as first_usage:
        interrupted = service.execute_entry(entry)
    interrupted_state = _run_state(service, interrupted.run_id or "")
    _emit_trace(
        "compound_before_confirmation",
        interrupted,
        interrupted_state,
        service=service,
        llm_call_count=first_usage.call_count,
        trace_archive=trace_archive,
        nodeid=request.node.nodeid,
    )

    assert first_usage.call_count >= 1, "the E2E must call the configured live model"
    assert interrupted_state.accepted_task_analysis is not None
    analysis = interrupted_state.accepted_task_analysis.analysis
    assert analysis.outcome == "ready"
    assert [goal.result_contract for goal in analysis.goals] == [
        "external_state",
        "response",
    ]
    assert any(
        relation.predecessor_goal_id == "goal_1"
        and relation.successor_goal_id == "goal_2"
        and relation.kind == "consumes_output"
        for relation in analysis.relations
    )

    assert interrupted.run_status == "blocked_approval"
    assert interrupted.pending_confirmation is not None
    assert interrupted_state.control.pending_interaction is not None
    assert interrupted_state.control.pending_interaction.kind == "confirmation_required"
    assert interrupted_state.control.pending_interaction.authorization_digest
    assert "confirmation_required" in _agent_event_types(interrupted_state)
    task = interrupted_state.task_contract
    assert task is not None
    assert task.result_contract == "compound"
    second_goal = task.goal_graph.goals[1]
    assert any(
        dependency.dependency_goal_id == "goal_1"
        and dependency.kind == "consumes_output"
        for dependency in second_goal.dependencies
    )
    assert task.mutation_intent is not None
    assert task.mutation_intent.requires_confirmation is True
    assert "ingest" in task.mutation_intent.operations
    assert interrupted_state.task_runtime is not None
    assert interrupted_state.task_runtime.goal_states["goal_2"].status == "pending"
    assert service.store.list_notes(user_id) == []
    persisted_before = service.runtime.control_plane_store.list_commands(
        interrupted.run_id or ""
    )
    assert persisted_before
    assert all(command.derivation_record.derivation_kind == "command_resolution" for command in persisted_before)
    assert any(
        command.authorization_digest
        == interrupted_state.control.pending_interaction.authorization_digest
        for command in persisted_before
    )

    with collect_llm_usage() as resume_usage:
        completed = service.resume_entry(
            interrupted.run_id or "",
            interrupted.thread_id or "",
            "confirm",
            user_id,
        )
    completed_state = _run_state(service, completed.run_id or "")
    _emit_trace(
        "compound_after_confirmation",
        completed,
        completed_state,
        service=service,
        llm_call_count=resume_usage.call_count,
        trace_archive=trace_archive,
        nodeid=request.node.nodeid,
    )

    assert completed.run_status == "completed"
    assert completed_state.task_runtime is not None
    assert completed_state.task_runtime.lifecycle == "completed"
    assert {
        goal_id: runtime.status
        for goal_id, runtime in completed_state.task_runtime.goal_states.items()
    } == {"goal_1": "verified", "goal_2": "verified"}
    assert set(completed_state.verification_reports) == {"goal_1", "goal_2"}
    assert all(
        report.status == "passed"
        for report in completed_state.verification_reports.values()
    )
    assert completed_state.completion_report is not None
    assert completed_state.completion_report.status == "complete"
    assert completed_state.final_answer_proposal is not None
    assert completed_state.final_answer_admission is not None
    assert completed_state.final_answer_admission.verdict == "accepted"
    assert set(completed_state.completion_report.verified_goal_ids) == {
        "goal_1",
        "goal_2",
    }
    assert any(
        grant.required_confirmation_ref
        for grant in completed_state.execution_grants.values()
    )
    assert all(
        grant.authorization_digest and grant.execution_command_digest
        for grant in completed_state.execution_grants.values()
    )
    assert completed_state.execution_fact_reports
    assert all(
        report.execution_command_digest
        for report in completed_state.execution_fact_reports.values()
    )
    assert any(
        release_fact in note.content for note in service.store.list_notes(user_id)
    )
    assert "周五" in completed.reply_text and "20:00" in completed.reply_text
    assert "goal_verified" in _execution_event_types(completed_state)
    assert _execution_event_types(completed_state)[-1] == "task_completed"


def test_missing_unsupported_mutation_input_never_fabricates_success_live(
    service: AgentService,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    user_id = "live-e2e-unsupported-user"
    entry = EntryInput(
        text=(
            "把我这次请求里附带的音频剪成 30 秒视频，"
            "然后发送到 live-e2e@example.com。"
        ),
        user_id=user_id,
        session_id=f"live-e2e-unsupported-{uuid4().hex}",
        source_platform="live_e2e",
    )

    with collect_llm_usage() as usage:
        result = service.execute_entry(entry)
    state = _run_state(service, result.run_id or "")
    _emit_trace(
        "unsupported_mutation",
        result,
        state,
        service=service,
        llm_call_count=usage.call_count,
        trace_archive=trace_archive,
        nodeid=request.node.nodeid,
    )

    assert usage.call_count >= 1, "the E2E must call the configured live model"
    assert state.accepted_task_analysis is not None
    assert state.accepted_task_analysis.analysis.outcome in {"clarify", "rejected", "ready"}
    assert service.store.list_notes(user_id) == []
    assert state.verification_reports == {}
    assert state.completion_report is None or state.completion_report.status != "complete"
    assert "task_completed" not in _execution_event_types(state)
    if state.task_runtime is not None:
        assert all(
            runtime.status != "verified"
            for runtime in state.task_runtime.goal_states.values()
        )
        if state.task_runtime.lifecycle == "active":
            assert result.run_status in {"waiting", "blocked_approval", "failed"}
            if result.run_status != "failed":
                assert result.pending_confirmation is not None
        else:
            assert state.task_runtime.lifecycle == "terminated"
            assert "task_terminated" in _execution_event_types(state)
