from __future__ import annotations

from evals.e2e_quality.failure_diagnostics import diagnose_earliest_failure


_SOURCE_GROUPS = (("developers.openai.com",), ("modelcontextprotocol.io",))


def _agent(status: str, *, text: str = "") -> dict[str, object]:
    return {
        "kind": "agent_artifact",
        "status": status,
        "payload": {"content_excerpt": text},
    }


def _feedback(reason_code: str) -> dict[str, object]:
    return {"kind": "decision_feedback", "reason_code": reason_code}


def test_first_agent_failure_wins_over_later_argument_rejection() -> None:
    diagnostic = diagnose_earliest_failure(
        delivered=False,
        entry_error=None,
        interaction_trace={
            "inputs": [_agent("failed"), _feedback("invalid_arguments")]
        },
        required_source_groups=_SOURCE_GROUPS,
    )

    assert diagnostic.model_dump(mode="json") == {
        "status": "blocked",
        "stage": "agent_execution",
        "input_index": 0,
        "reason_code": "failed",
    }


def test_first_argument_rejection_wins_over_later_agent_failure() -> None:
    diagnostic = diagnose_earliest_failure(
        delivered=False,
        entry_error=None,
        interaction_trace={
            "inputs": [_feedback("invalid_arguments"), _agent("failed")]
        },
        required_source_groups=_SOURCE_GROUPS,
    )

    assert diagnostic.stage == "admission"
    assert diagnostic.input_index == 0
    assert diagnostic.reason_code == "invalid_arguments"


def test_context_feedback_that_allows_the_loop_to_continue_is_not_a_blocker() -> None:
    diagnostic = diagnose_earliest_failure(
        delivered=False,
        entry_error=None,
        interaction_trace={
            "inputs": [
                {
                    "kind": "decision_feedback",
                    "action_id": "interaction_turn",
                    "reason_code": "verification_capability_unavailable",
                },
                _feedback("working_plan_missing"),
            ]
        },
        required_source_groups=_SOURCE_GROUPS,
    )

    assert diagnostic.stage == "admission"
    assert diagnostic.input_index == 1
    assert diagnostic.reason_code == "working_plan_missing"


def test_rejection_after_successful_observation_is_post_observation() -> None:
    diagnostic = diagnose_earliest_failure(
        delivered=False,
        entry_error=None,
        interaction_trace={
            "inputs": [
                _agent("succeeded", text="https://developers.openai.com"),
                _feedback("invalid_arguments"),
                _agent("failed"),
            ]
        },
        required_source_groups=_SOURCE_GROUPS,
    )

    assert diagnostic.stage == "post_observation"
    assert diagnostic.input_index == 1


def test_required_sources_without_a_final_result_is_completion_failure() -> None:
    diagnostic = diagnose_earliest_failure(
        delivered=False,
        entry_error=None,
        interaction_trace={
            "inputs": [
                _agent(
                    "succeeded",
                    text=(
                        "https://developers.openai.com and "
                        "https://modelcontextprotocol.io"
                    ),
                )
            ]
        },
        required_source_groups=_SOURCE_GROUPS,
    )

    assert diagnostic.stage == "completion"
    assert diagnostic.input_index is None


def test_missing_ordered_evidence_is_not_guessed_from_final_text() -> None:
    diagnostic = diagnose_earliest_failure(
        delivered=False,
        entry_error=None,
        interaction_trace={"inputs": []},
        required_source_groups=_SOURCE_GROUPS,
    )

    assert diagnostic.status == "unclassified"
    assert diagnostic.stage is None


def test_entry_error_precedes_any_trace_input() -> None:
    diagnostic = diagnose_earliest_failure(
        delivered=False,
        entry_error={"type": "TimeoutError"},
        interaction_trace={"inputs": [_feedback("invalid_arguments")]},
        required_source_groups=_SOURCE_GROUPS,
    )

    assert diagnostic.stage == "entry"
    assert diagnostic.input_index is None
    assert diagnostic.reason_code == "TimeoutError"
