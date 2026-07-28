"""Application-path lifecycle boundaries for durable Investigation Projects."""

from __future__ import annotations

import pytest

from evals.e2e_quality.investigation_harness import InvestigationScenarioHarness


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
