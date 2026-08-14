"""Durable Investigation Project user-result E2E scenarios.

The scenario harness composes production domain/application/store/gateway
components and substitutes only external provider ports with contract-tested,
deterministic adapters.
"""

from __future__ import annotations

import pytest

from evals.runtime_conformance.investigation_project.investigation_harness import (
    InvestigationScenarioHarness,
)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("clean_postgres_business_tables"),
]


def test_lt01_complete_architecture_investigation(postgres_url, temp_dir):
    result = InvestigationScenarioHarness(postgres_url, temp_dir).complete_investigation()

    assert result.state == "completed"
    assert result.requirement_coverage == {
        "architecture": "verified",
        "security": "verified",
        "cost": "verified",
        "migration": "verified",
    }
    assert result.final_artifact_ref
    assert result.execution_refs
    assert result.unadmitted_evidence_refs == ()
    assert result.cross_scope_refs == ()


def test_lt03_steering_preserves_frozen_work_and_user_requirements(postgres_url, temp_dir):
    result = InvestigationScenarioHarness(postgres_url, temp_dir).steering_revision()

    assert result.user_requirement_versions == 2
    assert result.waived_requirement_refs == ("cost",)
    assert result.added_requirement_refs == ("migration-order",)
    assert result.reused_outcome_refs
    assert result.overwritten_frozen_refs == ()
    assert result.late_evidence_refs == result.quarantined_evidence_refs


def test_lt04_parallel_children_join_only_after_verified_outcomes(postgres_url, temp_dir):
    result = InvestigationScenarioHarness(postgres_url, temp_dir).parallel_join()

    assert len(result.first_dispatch_batch) == 2
    assert result.synthesis_dispatch_sequence > max(result.verified_outcome_sequences)
    assert result.synthesis_dispatch_before_join is False


def test_lt05_external_delegation_waits_for_digest_bound_approval(postgres_url, temp_dir):
    result = InvestigationScenarioHarness(postgres_url, temp_dir).governed_delegation()

    assert result.state_while_other_work_ready == "active"
    assert result.waiting_reason == "approval_required"
    assert result.provider_calls_before_approval == 0
    assert result.authorization_digest == result.confirmation_authorization_digest
    assert result.command_digest == result.receipt_command_digest
    assert result.provider_calls_after_approval == 1


def test_lt06_budget_exhaustion_pauses_with_partial_coverage(postgres_url, temp_dir):
    result = InvestigationScenarioHarness(postgres_url, temp_dir).budget_exhaustion()

    assert result.state == "paused"
    assert result.completed_requirement_refs
    assert result.unmet_requirement_refs
    assert result.over_budget_dispatches == 0
    assert result.completion_report is None
    assert result.partial_artifact_ref


def test_lt07_cancel_quarantines_late_result(postgres_url, temp_dir):
    result = InvestigationScenarioHarness(postgres_url, temp_dir).cancel_and_late_result()

    assert result.state == "cancelled"
    assert result.cancelled_child_refs
    assert result.late_artifact_ref
    assert result.late_artifact_ref in result.quarantined_artifact_refs
    assert result.post_cancel_dispatches == 0


def test_lt08_security_scope_isolation_survives_recovery(postgres_url, temp_dir):
    result = InvestigationScenarioHarness(postgres_url, temp_dir).scope_isolation()

    assert result.state == "completed"
    assert result.scope_violations == ()
    assert result.cross_scope_refs == ()
    assert result.provider_scope_assertions_passed


def test_lt11_missing_capability_fails_closed_without_fallback(postgres_url, temp_dir):
    result = InvestigationScenarioHarness(postgres_url, temp_dir).capability_missing()

    assert result.state == "paused"
    assert result.missing_contract == "notion.retrieve_page_markdown"
    assert result.dispatches == ()
    assert result.fallback_dispatches == ()


def test_lt12_observation_revises_only_unfrozen_dynamic_plan(postgres_url, temp_dir):
    result = InvestigationScenarioHarness(postgres_url, temp_dir).observation_driven_revision()

    assert result.plan_versions == 2
    assert result.reused_completed_scan
    assert result.superseded_subgoal_ref
    assert result.added_subgoal_refs == ("message-consistency", "compensation-transaction")
    assert result.repeated_scan_dispatches == 0
    assert result.dynamic_invalid_dispatches < result.fixed_workflow_invalid_dispatches
