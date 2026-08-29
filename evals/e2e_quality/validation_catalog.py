"""Canonical cross-cutting validation suites over existing E2E evidence.

Evidence classification remains single-owner in ``evidence_catalog``.  This
module only declares which already-catalogued E2E traces can validate a
runtime mechanism independently from the test's product outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from evals.e2e_quality.evidence_catalog import EVIDENCE_CASES


class ValidationSuiteId(str, Enum):
    TOOL_CALLING_PROTOCOL = "tool_calling_protocol"
    MCP_DISPATCH = "mcp_dispatch"
    A2A_ARTIFACT_RETURN = "a2a_artifact_return"
    NARROW_RESEARCH_ROUTING = "narrow_research_routing"


class ValidationCheckKind(str, Enum):
    TOOL_RESULT_COUNT = "tool_result_count"
    AGENT_ARTIFACT_COUNT = "agent_artifact_count"
    AGENT_OBSERVATION_COUNT = "agent_observation_count"
    FORBIDDEN_FEEDBACK_REASONS = "forbidden_feedback_reasons"


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    check_id: str
    kind: ValidationCheckKind
    capability_ids: frozenset[str] = frozenset()
    minimum_count: int = 0
    maximum_count: int | None = None
    accepted_statuses: frozenset[str] = frozenset()
    reason_codes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.check_id.strip():
            raise ValueError("validation check requires check_id")
        if self.minimum_count < 0:
            raise ValueError("validation check minimum_count cannot be negative")
        if self.maximum_count is not None and self.maximum_count < self.minimum_count:
            raise ValueError("validation check maximum_count cannot be below minimum_count")
        count_kinds = {
            ValidationCheckKind.TOOL_RESULT_COUNT,
            ValidationCheckKind.AGENT_ARTIFACT_COUNT,
            ValidationCheckKind.AGENT_OBSERVATION_COUNT,
        }
        if self.kind in count_kinds and (
            not self.capability_ids
            or (self.minimum_count < 1 and self.maximum_count is None)
        ):
            raise ValueError("count check requires capability ids and a count bound")
        if (
            self.kind is ValidationCheckKind.FORBIDDEN_FEEDBACK_REASONS
            and not self.reason_codes
        ):
            raise ValueError("feedback check requires forbidden reason codes")


@dataclass(frozen=True, slots=True)
class ValidationCaseContract:
    evidence_id: str
    checks: tuple[ValidationCheck, ...]

    def __post_init__(self) -> None:
        if not self.checks:
            raise ValueError("validation case requires at least one critical check")
        check_ids = tuple(check.check_id for check in self.checks)
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("validation case check ids must be unique")


@dataclass(frozen=True, slots=True)
class ValidationSuite:
    suite_id: ValidationSuiteId
    purpose: str
    cases: tuple[ValidationCaseContract, ...]

    def __post_init__(self) -> None:
        if not self.purpose.strip() or not self.cases:
            raise ValueError("validation suite requires purpose and cases")
        evidence_ids = tuple(case.evidence_id for case in self.cases)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("validation suite cannot repeat an evidence case")


_PROTOCOL_REJECTION_REASONS = frozenset({
    "duplicate_action_id",
    "invalid_arguments",
    "working_plan_missing",
    "working_plan_review_required",
})


def _tool_protocol_case(
    evidence_id: str,
    capability_id: str,
    *,
    minimum_count: int = 1,
) -> ValidationCaseContract:
    return ValidationCaseContract(
        evidence_id=evidence_id,
        checks=(
            ValidationCheck(
                check_id="action_reached_gateway",
                kind=ValidationCheckKind.TOOL_RESULT_COUNT,
                capability_ids=frozenset({capability_id}),
                minimum_count=minimum_count,
            ),
            ValidationCheck(
                check_id="no_action_protocol_rejection",
                kind=ValidationCheckKind.FORBIDDEN_FEEDBACK_REASONS,
                reason_codes=_PROTOCOL_REJECTION_REASONS,
            ),
        ),
    )


VALIDATION_SUITES: tuple[ValidationSuite, ...] = (
    ValidationSuite(
        suite_id=ValidationSuiteId.TOOL_CALLING_PROTOCOL,
        purpose=(
            "A provider-native action is decoded, admitted and dispatched without "
            "an action-schema or plan-binding rejection. Provider success and the "
            "final user outcome are separate verdicts."
        ),
        cases=(
            _tool_protocol_case(
                "L01.complex_loop_http",
                "search_personal_knowledge",
            ),
            _tool_protocol_case(
                "L06.complex_loop_http",
                "verify_interaction_draft",
            ),
            _tool_protocol_case(
                "RUN-001.baseline",
                "external_records.read_one",
                minimum_count=2,
            ),
            _tool_protocol_case(
                "E16.capability_profile",
                "github.get_file_contents",
            ),
        ),
    ),
    ValidationSuite(
        suite_id=ValidationSuiteId.MCP_DISPATCH,
        purpose=(
            "An admitted action reaches an MCP-backed tool boundary. A remote "
            "authorization or provider failure does not invalidate dispatch."
        ),
        cases=(
            ValidationCaseContract(
                evidence_id="RUN-001.baseline",
                checks=(
                    ValidationCheck(
                        check_id="two_frozen_mcp_dispatches",
                        kind=ValidationCheckKind.TOOL_RESULT_COUNT,
                        capability_ids=frozenset({"external_records.read_one"}),
                        minimum_count=2,
                    ),
                ),
            ),
            ValidationCaseContract(
                evidence_id="E16.capability_profile",
                checks=(
                    ValidationCheck(
                        check_id="real_github_mcp_dispatch",
                        kind=ValidationCheckKind.TOOL_RESULT_COUNT,
                        capability_ids=frozenset({"github.get_file_contents"}),
                        minimum_count=1,
                    ),
                ),
            ),
        ),
    ),
    ValidationSuite(
        suite_id=ValidationSuiteId.A2A_ARTIFACT_RETURN,
        purpose=(
            "The real specialist path returns one succeeded AgentArtifact to the "
            "parent. Parent synthesis and the final user outcome remain separate."
        ),
        cases=(
            ValidationCaseContract(
                evidence_id="L04.complex_loop_http",
                checks=(
                    ValidationCheck(
                        check_id="specialist_artifact_returned",
                        kind=ValidationCheckKind.AGENT_ARTIFACT_COUNT,
                        capability_ids=frozenset({"gpt_researcher"}),
                        minimum_count=1,
                        accepted_statuses=frozenset({"succeeded"}),
                    ),
                ),
            ),
        ),
    ),
    ValidationSuite(
        suite_id=ValidationSuiteId.NARROW_RESEARCH_ROUTING,
        purpose=(
            "A narrow mixed-evidence request uses the parent Conversation's direct "
            "personal and Web reads without delegating the whole request. The Product "
            "E2E outcome remains an independent verdict."
        ),
        cases=(
            ValidationCaseContract(
                evidence_id="ASK-001B.product_http",
                checks=(
                    ValidationCheck(
                        check_id="personal_evidence_read",
                        kind=ValidationCheckKind.TOOL_RESULT_COUNT,
                        capability_ids=frozenset({"search_personal_knowledge"}),
                        minimum_count=1,
                        accepted_statuses=frozenset({"succeeded"}),
                    ),
                    ValidationCheck(
                        check_id="official_web_evidence_read",
                        kind=ValidationCheckKind.TOOL_RESULT_COUNT,
                        capability_ids=frozenset({"web_search"}),
                        minimum_count=1,
                        accepted_statuses=frozenset({"succeeded"}),
                    ),
                    ValidationCheck(
                        check_id="no_whole_request_delegation",
                        kind=ValidationCheckKind.AGENT_OBSERVATION_COUNT,
                        capability_ids=frozenset({"gpt_researcher"}),
                        maximum_count=0,
                    ),
                ),
            ),
        ),
    ),
)

VALIDATION_SUITE_BY_ID = {suite.suite_id: suite for suite in VALIDATION_SUITES}


def validate_validation_catalog() -> None:
    evidence_ids = {case.evidence_id for case in EVIDENCE_CASES}
    suite_ids = tuple(suite.suite_id for suite in VALIDATION_SUITES)
    if len(suite_ids) != len(set(suite_ids)):
        raise ValueError("validation suite ids must be unique")
    unknown = sorted({
        case.evidence_id
        for suite in VALIDATION_SUITES
        for case in suite.cases
        if case.evidence_id not in evidence_ids
    })
    if unknown:
        raise ValueError(f"validation suites reference unknown evidence: {unknown}")


validate_validation_catalog()


__all__ = [
    "VALIDATION_SUITE_BY_ID",
    "VALIDATION_SUITES",
    "ValidationCaseContract",
    "ValidationCheck",
    "ValidationCheckKind",
    "ValidationSuite",
    "ValidationSuiteId",
    "validate_validation_catalog",
]
