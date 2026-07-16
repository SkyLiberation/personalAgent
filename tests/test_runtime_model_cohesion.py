from __future__ import annotations

from pathlib import Path

from personal_agent.kernel.contracts.agent import ChildAgentRunOutcome
from personal_agent.kernel.contracts.agentic import (
    ContextInventory,
    GoalDefinition,
    GoalGraphDefinition,
    GoalRuntimeState,
    TaskContract,
    TaskRuntimeProjection,
    materialize_goals,
    ResourceRequirement,
    SuccessCriterion,
    TaskConstraints,
)
from personal_agent.kernel.contracts.capability import (
    Capability,
    CapabilityRequirement,
    CapabilityResolutionDecision,
)
from personal_agent.kernel.contracts.execution import (
    ExecutableInvocation,
    InvocationAttemptState,
)
from personal_agent.kernel.contracts.planning import (
    PlanRuntimeProjection,
    PlannerExecutionProfile,
    PlanningLimits,
    PlanningUsage,
)
from personal_agent.kernel.contracts.procedure import (
    ProcedureInvocation,
    ProcedureRunProjection,
)


def test_goal_definition_and_runtime_have_one_owner_each() -> None:
    task = TaskContract(
        task_id="task-1",
        user_goal="explain",
        result_contract="response",
        goal_graph=GoalGraphDefinition(goals=(GoalDefinition(
            goal_id="goal-1",
            description="explain",
        ),)),
    )
    runtime = TaskRuntimeProjection(
        task_id=task.task_id,
        task_revision=task.revision,
        goal_states={"goal-1": GoalRuntimeState(status="active")},
    )

    view = materialize_goals(task, runtime)[0]

    assert view.description == "explain"
    assert view.status == "active"
    assert "description" not in GoalRuntimeState.model_fields
    assert "status" not in GoalDefinition.model_fields


def test_projection_models_do_not_embed_event_logs_or_requests() -> None:
    assert "events" not in PlanRuntimeProjection.model_fields
    assert "request" not in CapabilityResolutionDecision.model_fields
    assert "lifecycle_events" not in CapabilityResolutionDecision.model_fields
    assert "artifacts" not in ChildAgentRunOutcome.__dataclass_fields__


def test_limits_usage_and_invocation_attempts_are_separate() -> None:
    assert not set(PlanningLimits.model_fields).intersection(PlanningUsage.model_fields)
    assert PlannerExecutionProfile.model_fields["limits"].annotation is PlanningLimits
    invocation = ExecutableInvocation(
        step_id="invoke-1",
        action_type="compose",
        description="compose answer",
        attempt=InvocationAttemptState(status="running"),
    )
    assert invocation.attempt.status == "running"
    assert "status" not in ExecutableInvocation.model_fields


def test_context_inventory_has_one_item_collection() -> None:
    assert set(ContextInventory.model_fields) == {"items"}


def test_resource_and_capability_models_compose_shared_value_objects() -> None:
    assert {"selector", "operation_scope", "provider_constraint"}.issubset(
        ResourceRequirement.model_fields
    )
    assert {"selector", "operation_scope", "provider_constraint"}.issubset(
        CapabilityRequirement.model_fields
    )
    assert {"selector", "operation_scope"}.issubset(Capability.model_fields)
    for model in (ResourceRequirement, CapabilityRequirement, Capability):
        assert "semantic_domains" not in model.model_fields
        assert "resource_types" not in model.model_fields


def test_definition_tree_value_objects_are_frozen() -> None:
    for model in (ResourceRequirement, SuccessCriterion, TaskConstraints):
        assert model.model_config.get("frozen") is True


def test_mutation_operation_taxonomy_has_one_owner() -> None:
    source_root = Path(__file__).parents[1] / "src" / "personal_agent"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in source_root.rglob("*.py")
    )
    assert source.count('"create", "update", "delete", "ingest", "repair"') == 1


def test_procedure_invocation_and_projection_do_not_mirror_definition_input() -> None:
    assert {"invocation_id", "procedure", "goal_id", "input"}.issubset(
        ProcedureInvocation.model_fields
    )
    assert "input" not in ProcedureRunProjection.model_fields
    assert "goal_id" not in ProcedureRunProjection.model_fields
    assert "task_id" not in ProcedureRunProjection.model_fields


def test_removed_runtime_model_names_do_not_reappear() -> None:
    source_root = Path(__file__).parents[1] / "src" / "personal_agent"
    removed = (
        "class TaskSpec",
        "class ExecutionLedger",
        "class ExecutionLedgerItem",
        "class PlanningBudget",
        "class ContextEnvelope",
        "class AgentGraphState",
        "class ExecutionStep",
        "class StepRunState",
        "class CapabilityResolution(",
        "class ProcedureSpec(",
        "class ProcedureCall(",
        "class ProcedureInstance(",
        "class ResearchState",
        "class ResearchRun(",
        "class ResearchSubscription(",
        "class ResearchDecision(",
    )
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in source_root.rglob("*.py")
    )
    for name in removed:
        assert name not in source
    assert 'goal_id: str = ""' not in source
