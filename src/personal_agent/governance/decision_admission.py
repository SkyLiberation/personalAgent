"""Deterministic validation for model-proposed executive decisions."""

from __future__ import annotations

from personal_agent.runtime.contracts.task import (
    TaskRuntimeProjection,
    TaskContract,
    materialize_goals,
)
from personal_agent.runtime.contracts.control import (
    AcceptedControlCommand,
    ControlProposal,
    ControlState,
    ControlDecision,
    DelegateDecision,
    ExecuteBoundedActionDecision,
    InvokeProcedureDecision,
    RequestCapabilityAcquisitionDecision,
)
from personal_agent.governance.contracts.admission import (
    GovernanceSnapshotRef,
    StageAdmissionDecision,
)
from personal_agent.kernel.contracts.resource import MUTATING_OPERATIONS


class _DecisionDenied(ValueError):
    pass


class DecisionValidator:
    def admit(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        proposal: ControlProposal,
        control_state: ControlState | None = None,
    ) -> StageAdmissionDecision:
        try:
            self._validate(task, ledger, proposal.decision, control_state)
            verdict = "accepted"
            reasons = ("decision_within_task_authority",)
        except _DecisionDenied as exc:
            verdict = "denied"
            reasons = (str(exc),)
        return StageAdmissionDecision(
            proposal_ref=proposal.proposal_id,
            verdict=verdict,
            effective_constraint_refs=(
                f"task:{task.task_id}:revision:{task.revision}",
                f"goal:{proposal.decision.target_goal_id}",
            ),
            reason_codes=reasons,
            snapshot=GovernanceSnapshotRef(
                task_revision=task.revision,
                runtime_revision=ledger.revision,
                policy_revision="decision-admission:v2",
            ),
        )

    def _validate(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        decision: ControlDecision,
        control_state: ControlState | None,
    ) -> None:
        goals = {
            item.goal_id: item for item in materialize_goals(task, ledger)
        }
        if decision.target_goal_id not in goals and decision.action not in {"finish", "terminate"}:
            raise _DecisionDenied("unknown_goal")
        goal = goals.get(decision.target_goal_id)
        goal_procedures = tuple(
            candidate for candidate in (control_state.procedure_candidates if control_state else ())
            if candidate.goal_id == decision.target_goal_id
            and candidate.status in {"eligible", "mandatory"}
        )
        if (
            any(candidate.status == "mandatory" for candidate in goal_procedures)
            and not isinstance(decision, InvokeProcedureDecision)
            and decision.action not in {"terminate", "clarify", "request_confirmation"}
        ):
            raise _DecisionDenied("mandatory_procedure_bypass")
        if (
            goal is not None
            and decision.action not in {"finish", "terminate"}
        ):
            unmet_dependencies = tuple(
                dependency.dependency_goal_id
                for dependency in goal.dependencies
                if dependency.blocks_execution and (
                    dependency.dependency_goal_id not in goals
                    or goals[dependency.dependency_goal_id].status not in {"verified", "degraded"}
                )
            )
            if unmet_dependencies:
                raise _DecisionDenied("goal_dependencies_unmet")
        if (
            goal is not None
            and goal.status in {"verified", "degraded", "abandoned"}
            and decision.action not in {"finish", "terminate"}
        ):
            raise _DecisionDenied("terminal_goal_targeted")
        if isinstance(decision, ExecuteBoundedActionDecision):
            action = decision.bounded_action
            access = action.proposed_resource_access
            if action.goal_id != decision.target_goal_id:
                raise _DecisionDenied("action_goal_mismatch")
            if access.side_effect_class != "none" and (
                action.execution_intent != "commit"
                or task.mutation_intent is None
                or not access.write_set
                or action.requirement is None
                or not set(action.requirement.operations).intersection(
                    MUTATING_OPERATIONS
                )
            ):
                raise _DecisionDenied("mutation_authority_incomplete")
            if action.max_tool_calls > task.constraints.max_provider_calls:
                raise _DecisionDenied("task_provider_budget_exceeded")
            if (
                control_state is not None
                and action.max_tool_calls > control_state.remaining_provider_calls
            ):
                raise _DecisionDenied("remaining_provider_budget_exceeded")
        if isinstance(decision, InvokeProcedureDecision):
            call = decision.procedure_invocation
            if goal is None or call.goal_id != goal.goal_id:
                raise _DecisionDenied("procedure_goal_mismatch")
            candidate = next((
                item for item in goal_procedures
                if item.procedure_id == call.procedure.procedure_id
                and item.version == call.procedure.version
            ), None)
            if candidate is None:
                raise _DecisionDenied("procedure_not_eligible")
            if control_state is not None and control_state.remaining_provider_calls < 1:
                raise _DecisionDenied("procedure_provider_budget_exhausted")
        if isinstance(decision, RequestCapabilityAcquisitionDecision):
            allowed_operations = {
                operation
                for resource in task.resources_for_goal(decision.target_goal_id)
                for operation in resource.required_operations
            }
            requested = set(decision.requirement.operations)
            if allowed_operations and not requested.issubset(allowed_operations):
                raise _DecisionDenied("capability_acquisition_expands_operations")
        if (
            isinstance(decision, DelegateDecision)
            and control_state is not None
            and decision.subtask.max_provider_calls > control_state.remaining_provider_calls
        ):
            raise _DecisionDenied("delegation_provider_budget_exceeded")


class AcceptedCommandCompiler:
    def compile(
        self,
        proposal: ControlProposal,
        admission: StageAdmissionDecision,
    ) -> AcceptedControlCommand:
        if admission.proposal_ref != proposal.proposal_id:
            raise ValueError("admission does not reference this proposal")
        if admission.verdict != "accepted":
            raise ValueError("only accepted proposals compile to commands")
        proof = admission.monotonicity
        if proof.operations_expanded or proof.resources_expanded or proof.budgets_expanded:
            raise ValueError("admission proof permits authority expansion")
        return AcceptedControlCommand(
            proposal_ref=proposal.proposal_id,
            admission_ref=admission.admission_id,
            decision=proposal.decision,
        )

__all__ = ["AcceptedCommandCompiler", "DecisionValidator"]
