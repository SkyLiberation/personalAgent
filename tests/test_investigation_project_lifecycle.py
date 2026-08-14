"""Application-path lifecycle boundaries for durable Investigation Projects."""

from __future__ import annotations

import pytest

from evals.runtime_conformance.investigation_project.investigation_harness import (
    InvestigationScenarioHarness,
)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("clean_postgres_business_tables"),
]


def test_user_pause_resume_does_not_bypass_system_pause(postgres_url, temp_dir):
    result = InvestigationScenarioHarness(
        postgres_url,
        temp_dir,
    ).pause_resume_boundaries()

    assert result.initial_state == "active"
    assert result.paused_state == "paused"
    assert result.paused_reason == "user_paused"
    assert result.recovery_enqueues == 0
    assert result.resumed_state == "active"
    assert result.completed_state == "completed"
    assert result.system_paused_state == "paused"
    assert result.system_paused_reason != "user_paused"
    assert "typed repair" in result.system_resume_error


def test_agent_submission_outcome_unknown_pauses_without_blind_retry(
    postgres_url,
    temp_dir,
):
    result = InvestigationScenarioHarness(
        postgres_url,
        temp_dir,
    ).outcome_unknown_fails_closed()

    assert result.state == "paused"
    assert [item.reason for item in result.waiting_reasons] == ["outcome_unknown"]
    assert result.provider_submissions == 0
    assert result.outcomes == ()


def test_completing_state_recovers_without_repeating_final_synthesis(
    postgres_url,
    temp_dir,
):
    result = InvestigationScenarioHarness(
        postgres_url,
        temp_dir,
    ).completing_state_recovers_after_process_crash()

    assert result.crashed_state == "completing"
    assert result.completed_state == "completed"
    assert result.first_final_synthesis_calls == 1
    assert result.restarted_final_synthesis_calls == 0
    assert len(result.final_artifact_refs) == 1
    assert result.active_reservations == ()
    assert result.planner_calls_after_restart == 0


def test_final_verification_failure_pauses_without_repeating(
    postgres_url,
    temp_dir,
):
    result = InvestigationScenarioHarness(
        postgres_url,
        temp_dir,
    ).final_verification_failure_pauses_without_repeating()

    assert result.state == "paused"
    assert result.reason == "final_verification_failed"
    assert result.verification_calls == 1
    assert result.replayed_state == "paused"
    assert result.replayed_verification_calls == 1
    assert len(result.waiting_reasons) == 1
    assert result.waiting_reasons[0].logical_subgoal_id == "final-report"
    assert result.waiting_reasons[0].reason == "verification_repair"
    assert "source URLs and limitations" in result.waiting_reasons[0].detail


def test_cancelling_state_recovers_without_duplicate_provider_effect(
    postgres_url,
    temp_dir,
):
    result = InvestigationScenarioHarness(
        postgres_url,
        temp_dir,
    ).cancelling_state_recovers_after_process_crash()

    assert result.crashed_state == "cancelling"
    assert result.cancelled_state == "cancelled"
    assert result.cancel_effect_count == 1
    assert result.cancel_attempts == 2
    assert result.planner_calls_after_restart == 0


def test_verification_gap_requires_runnable_repair_without_replaying_frozen_work(
    postgres_url,
    temp_dir,
):
    result = InvestigationScenarioHarness(
        postgres_url,
        temp_dir,
    ).verification_gap_revision()

    assert result.state == "completed", result
    assert result.plan_versions == 2
    assert result.requirement_coverage == {"architecture": "verified"}
    assert result.original_dispatches == 1
    assert result.repair_dispatches == 1
    assert result.final_mapping == ("candidate-discovery-repair",)
    assert result.waiting_reasons == ()
    assert len(result.feedback_received) == 1
    assert "frozen unsatisfied execution" in result.feedback_received[0].required_repair


def test_repeated_equivalent_repair_feedback_pauses_at_configured_limit(
    postgres_url,
    temp_dir,
):
    result = InvestigationScenarioHarness(
        postgres_url,
        temp_dir,
    ).repeated_verification_repair_feedback()

    assert result.state == "paused"
    assert result.state_reason == "verification_repair"
    assert result.planner_calls == 3
    assert result.original_dispatches == 1
    assert result.repair_dispatches == 0


def test_execution_admission_rejection_repairs_locally_without_replanning(
    postgres_url,
    temp_dir,
):
    result = InvestigationScenarioHarness(
        postgres_url,
        temp_dir,
    ).execution_admission_repairs_locally()

    assert result.state == "completed"
    assert result.plan_version == 1
    assert result.planner_calls == 1
    assert result.proposer_calls == 2
    assert result.tool_dispatches == 1


def test_repeated_execution_admission_feedback_pauses_without_replanning(
    postgres_url,
    temp_dir,
):
    result = InvestigationScenarioHarness(
        postgres_url,
        temp_dir,
    ).repeated_execution_admission_feedback_pauses_locally()

    assert result.state == "paused"
    assert result.state_reason == "verification_repair"
    assert result.plan_version == 1
    assert result.planner_calls == 1
    assert result.proposer_calls == 2
    assert result.tool_dispatches == 0
    assert result.waiting_reasons[0].reason == "verification_repair"
    assert "repair limit reached" in result.waiting_reasons[0].detail


def test_transitive_frozen_dependency_deadlock_requests_a_new_plan_revision(
    postgres_url,
    temp_dir,
):
    result = InvestigationScenarioHarness(
        postgres_url,
        temp_dir,
    ).transitive_deadlock_replans_after_repair()

    assert result.state == "completed", result
    assert result.plan_version == 3
    assert result.trigger_kinds == ("verification_gap", "coverage_deadlock")
    assert result.final_mapping == ("candidate-discovery-repair",)
    assert result.original_dispatches == 1
    assert result.repair_dispatches == 1
    assert result.blocked_summary_dispatches == 0
    assert result.waiting_reasons == ()


def test_parallel_budget_admission_releases_prepared_work_and_pauses(
    postgres_url,
    temp_dir,
):
    result = InvestigationScenarioHarness(
        postgres_url,
        temp_dir,
    ).parallel_budget_exhaustion_fails_closed()

    assert result.state == "paused"
    assert result.state_reason == "budget_exhausted"
    assert [item.reason for item in result.waiting_reasons] == ["budget_exhausted"]
    assert result.first_dispatches == 0
    assert result.second_dispatches == 0
    assert result.completion_report is None
