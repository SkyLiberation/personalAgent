"""Process-boundary and idempotency E2E for Durable Investigation Project."""

from __future__ import annotations

import pytest

from evals.e2e_quality.investigation_harness import InvestigationScenarioHarness


pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("clean_postgres_business_tables"),
]


def test_lt02_command_dispatch_recovers_without_duplicate(postgres_url, temp_dir):
    result = InvestigationScenarioHarness(postgres_url, temp_dir).command_dispatch_recovery()

    assert result.state == "completed"
    assert result.provider_submission_count == 1
    assert result.command_digest == result.receipt_command_digest
    assert result.superseding_command_refs == ()
    assert result.replanned_after_crash is False


def test_lt10_child_submit_reconciles_stable_submission_key(postgres_url, temp_dir):
    result = InvestigationScenarioHarness(postgres_url, temp_dir).child_submit_recovery()

    assert result.state == "completed"
    assert result.provider_task_ids == (result.reconciled_provider_task_id,)
    assert result.provider_submission_count == 1
    assert result.planner_calls_after_crash == 0
    assert result.execution_proposer_calls_after_crash == 0


def test_lt13_async_create_and_read_only_recovery(postgres_url, temp_dir):
    result = InvestigationScenarioHarness(postgres_url, temp_dir).async_create_recovery()

    assert result.create_status_code == 202
    assert result.initial_state == "planning"
    assert result.project_ids == (result.project_id,)
    assert result.user_requirements_preserved
    assert result.committed_read_dispatch_count == 1
    assert result.state == "completed"
    assert result.final_artifact_ref
    assert result.report_status_code == 200
    assert result.report_content
