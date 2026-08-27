from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from evals.provider_diagnostics.agent_artifact_plan_finalization_001 import (
    FrozenFinalizationCase,
    evaluate_final_message,
)
from personal_agent.application.conversation.models import (
    ActionObservation,
    ConversationMessage,
    ConversationWorkingPlan,
    ConversationWorkingPlanStep,
    FinalMessage,
    InteractionTrace,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


def _case() -> FrozenFinalizationCase:
    plan = ConversationWorkingPlan(
        plan_id="wplan-finalization",
        revision=1,
        goal="Deliver the delegated result",
        steps=(
            ConversationWorkingPlanStep(
                step_id="s1",
                description="Research result",
                status="completed",
            ),
            ConversationWorkingPlanStep(
                step_id="s2",
                description="Parent synthesis",
                status="pending",
            ),
        ),
    )
    return FrozenFinalizationCase(
        repetition=1,
        source_archive=Path("archive"),
        source_checksum_digest="a" * 64,
        marker="PERF-DELEGATE-01-7Q9X",
        observed_urls=("https://example.com/source",),
        trace=InteractionTrace(
            interaction_run_ref="irun-finalization",
            conversation_id="conversation-finalization",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id="diagnostic-user",
            ),
            messages=(ConversationMessage(role="user", content="Delegate and answer."),),
            inputs=(
                ActionObservation(
                    kind="agent_artifact",
                    action_id="delegate-1",
                    capability_id="gpt_researcher",
                    status="succeeded",
                    payload={"status": "completed"},
                    plan_step_id="s1",
                ),
            ),
            working_plan=plan,
        ),
    )


def test_finalization_evaluation_requires_explicit_exact_resolution_ids():
    case = _case()
    valid = evaluate_final_message(
        FinalMessage(
            disposition="answer",
            message=(
                "Result https://example.com/source PERF-DELEGATE-01-7Q9X"
            ),
            resolved_plan_step_ids=("s2",),
        ),
        case=case,
    )
    invalid = evaluate_final_message(
        FinalMessage(
            disposition="answer",
            message="Result without an explicit resolution binding.",
        ),
        case=case,
    )

    assert valid["exact_resolution_ids"] is True
    assert valid["admission_accepted"] is True
    assert valid["plan_resolution_contract_satisfied"] is True
    assert valid["negative_control_empty_ids_rejected"] is True
    assert valid["negative_control_illegal_ids_rejected"] is True
    assert valid["output_has_public_marker"] is True
    assert valid["output_has_observed_url"] is True
    assert invalid["exact_resolution_ids"] is False
    assert invalid["admission_accepted"] is False
    assert invalid["plan_resolution_contract_satisfied"] is False


def test_finalization_evaluation_exposes_terminal_plan_extraneous_id_gap():
    case = _case()
    working_plan = case.trace.working_plan
    assert working_plan is not None
    terminal_plan = working_plan.model_copy(
        update={
            "steps": tuple(
                step.model_copy(update={"status": "completed"})
                for step in working_plan.steps
            )
        }
    )
    terminal_case = replace(
        case,
        trace=case.trace.model_copy(update={"working_plan": terminal_plan}),
    )

    evaluation = evaluate_final_message(
        FinalMessage(
            disposition="answer",
            message="Final result.",
            resolved_plan_step_ids=("s1",),
        ),
        case=terminal_case,
    )

    assert evaluation["admission_accepted"] is True
    assert evaluation["exact_resolution_ids"] is False
    assert evaluation["plan_resolution_contract_satisfied"] is False
    assert evaluation["negative_control_illegal_ids_rejected"] is False
