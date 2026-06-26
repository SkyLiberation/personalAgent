from __future__ import annotations

from .dataset import (
    ToolEvalCase,
    ToolExecutionEvalCase,
    ToolExecutionRunOutput,
    ToolRunOutput,
)
from .metrics import side_effects_exact
from .scorer import score_case, score_execution_case


def test_side_effects_exact_is_order_insensitive():
    assert side_effects_exact(["write_longterm", "external_network"], [
        "external_network",
        "write_longterm",
    ]) == 1.0


def test_score_case_detects_governance_drift():
    case = ToolEvalCase(
        id="tool-test",
        description="",
        business_scenario="",
        tool_name="delete_note",
        expected_exposure="workflow_activity",
        expected_risk_level="high",
        expected_requires_confirmation=True,
        expected_side_effects=["delete_longterm"],
        expected_permission_scope="memory:delete",
        expected_idempotency_key_required=True,
        expected_audit_required=True,
        expected_timeout_seconds=20.0,
        expected_max_retries=0,
        expected_rate_limit_per_minute=10,
    )
    run = ToolRunOutput(
        tool_name="delete_note",
        exposure="workflow_activity",
        risk_level="low",
        requires_confirmation=False,
        side_effects=["delete_longterm"],
        permission_scope="memory:delete",
        idempotency_key_required=False,
        audit_required=True,
        timeout_seconds=20.0,
        max_retries=0,
        rate_limit_per_minute=10,
    )

    score = score_case(case, run)

    assert score.risk_exact == 0.0
    assert score.confirmation_exact == 0.0
    assert score.idempotency_exact == 0.0
    assert score.overall_exact == 0.0


def test_score_execution_case_detects_artifact_and_replay_drift():
    case = ToolExecutionEvalCase(
        id="tool-exec-test",
        description="",
        tool_name="delete_note",
        args={},
        repeat_same_call=True,
        expected_ok=True,
        expected_error_kind=None,
        expected_data_keys=["deleted_note_id", "snapshot_id"],
        expected_repeat_ok=False,
        expected_repeat_error_kind="unrecoverable",
        expected_call_counts={"memory.delete_note_confirmed": 1},
    )
    run = ToolExecutionRunOutput(
        tool_name="delete_note",
        ok=True,
        error_kind=None,
        data_keys=["deleted_note_id"],
        repeat_ok=True,
        repeat_error_kind=None,
        call_counts={"memory.delete_note_confirmed": 2},
    )

    score = score_execution_case(case, run)

    assert score.outcome_exact == 1.0
    assert score.data_shape_match == 0.0
    assert score.repeat_exact == 0.0
    assert score.call_count_exact == 0.0
    assert score.overall_exact == 0.0
