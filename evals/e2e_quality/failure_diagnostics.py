"""Typed, execution-ordered diagnostics for Conversation product E2E reports."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FailureStage = Literal[
    "entry",
    "model_action",
    "admission",
    "tool_execution",
    "agent_execution",
    "post_observation",
    "completion",
]
FailureDiagnosticStatus = Literal["delivered", "blocked", "unclassified"]

_NON_BLOCKING_CONTEXT_FEEDBACK = frozenset({
    "background_requirement_not_grounded",
    "review_criteria_not_grounded",
    "verification_capability_unavailable",
})


class EarliestFailureDiagnostic(BaseModel):
    """The first blocking fact derivable from one ordered interaction trace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: FailureDiagnosticStatus
    stage: FailureStage | None = None
    input_index: int | None = Field(default=None, ge=0)
    reason_code: str = Field(min_length=1)

    @model_validator(mode="after")
    def _stage_matches_status(self) -> "EarliestFailureDiagnostic":
        if (self.status == "blocked") != (self.stage is not None):
            raise ValueError("only a blocked diagnostic has a failure stage")
        if self.input_index is not None and self.stage in {"entry", "completion"}:
            raise ValueError("entry and completion failures do not identify an input")
        return self


def diagnose_earliest_failure(
    *,
    delivered: bool,
    entry_error: dict[str, Any] | None,
    interaction_trace: dict[str, Any],
    required_source_groups: tuple[tuple[str, ...], ...] = (),
) -> EarliestFailureDiagnostic:
    """Derive the earliest blocker without reordering failures by error type."""

    if entry_error is not None:
        error_type = str(entry_error.get("type") or "entry_error")
        return EarliestFailureDiagnostic(
            status="blocked",
            stage="entry",
            reason_code=error_type,
        )

    inputs = interaction_trace.get("inputs")
    if not isinstance(inputs, (list, tuple)):
        return EarliestFailureDiagnostic(
            status="unclassified",
            reason_code="ordered_inputs_missing",
        )

    successful_observation_seen = False
    for index, item in enumerate(inputs):
        if not isinstance(item, dict):
            return EarliestFailureDiagnostic(
                status="unclassified",
                reason_code="ordered_input_invalid",
            )
        kind = item.get("kind")
        status = item.get("status")
        if kind == "decision_feedback":
            reason_code = str(item.get("reason_code") or "action_rejected")
            if reason_code in _NON_BLOCKING_CONTEXT_FEEDBACK:
                continue
            return EarliestFailureDiagnostic(
                status="blocked",
                stage=(
                    "post_observation"
                    if successful_observation_seen
                    else "admission"
                ),
                input_index=index,
                reason_code=reason_code,
            )
        if kind == "tool_result" and status in {"failed", "cancelled"}:
            return EarliestFailureDiagnostic(
                status="blocked",
                stage="tool_execution",
                input_index=index,
                reason_code=str(status),
            )
        if kind in {"agent_status", "agent_artifact"} and status in {
            "failed",
            "cancelled",
        }:
            return EarliestFailureDiagnostic(
                status="blocked",
                stage="agent_execution",
                input_index=index,
                reason_code=str(status),
            )
        if kind in {"context_evidence", "tool_result", "agent_artifact"} and (
            status == "succeeded"
        ):
            successful_observation_seen = True

    if delivered:
        return EarliestFailureDiagnostic(
            status="delivered",
            reason_code="user_outcome_delivered",
        )
    if required_source_groups and _source_groups_observed(
        inputs,
        required_source_groups,
    ):
        return EarliestFailureDiagnostic(
            status="blocked",
            stage="completion",
            reason_code="required_sources_observed_but_not_delivered",
        )
    return EarliestFailureDiagnostic(
        status="unclassified",
        reason_code="insufficient_ordered_failure_evidence",
    )


def _source_groups_observed(
    inputs: list[Any] | tuple[Any, ...],
    groups: tuple[tuple[str, ...], ...],
) -> bool:
    visible_payload = "\n".join(
        json.dumps(item.get("payload"), ensure_ascii=False, sort_keys=True, default=str)
        for item in inputs
        if isinstance(item, dict)
        and item.get("kind") in {"context_evidence", "tool_result", "agent_artifact"}
        and item.get("status") == "succeeded"
    ).casefold()
    return all(
        any(host.casefold() in visible_payload for host in group)
        for group in groups
    )


__all__ = [
    "EarliestFailureDiagnostic",
    "FailureDiagnosticStatus",
    "FailureStage",
    "diagnose_earliest_failure",
]
