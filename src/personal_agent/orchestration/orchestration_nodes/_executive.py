"""Nodes for the task-level executive control loop."""

from __future__ import annotations

from hashlib import sha256
import json
import logging

from langgraph.types import interrupt

from personal_agent.kernel.contracts.interaction import InteractionRequest
from personal_agent.runtime.contracts.task import (
    AttemptRef,
    ContextBudget,
    ContextItem,
    RuntimeSnapshotRef,
    TaskRuntimeProjection,
)
from personal_agent.capabilities.contracts.execution import (
    CapabilityRequirement,
    CapabilityEquivalenceClass,
    CapabilityRuntimeContext,
    ExecutionCapabilityRequest,
    ExecutionResolutionResult,
    CapabilitySelectionPolicy,
)
from personal_agent.execution.contracts.invocation import (
    DelegatedSubtaskInvocation,
    ExecutableInvocation,
)
from personal_agent.capabilities.contracts.grants import AtomicCapabilityGrant, ProcedureGrant
from personal_agent.governance.contracts.audit import DecisionAuditRecord
from personal_agent.runtime.contracts.control import (
    ActionOutcome,
    BoundedAction,
    CapabilityActionInput,
    CapabilityClassSummary,
    CapabilityGapObservation,
    ClarifyDecision,
    CompletionClaim,
    ControlProposal,
    DecisionBasis,
    DelegateActionInput,
    DelegateDecision,
    ExecuteBoundedActionDecision,
    FinishDecision,
    InvokeProcedureDecision,
    ObservationRef,
    ProposedResourceAccessPlan,
    ProcedureActionInput,
    RequestConfirmationDecision,
    RequestCapabilityAcquisitionDecision,
    TerminateDecision,
    observation_provenance,
    canonical_digest,
)
from personal_agent.capabilities.contracts.acquisition import CapabilityAcquisitionRequest
from personal_agent.runtime.contracts.planning import PlanRuntimeProjection
from personal_agent.capabilities.contracts.outcomes import (
    CapabilityEffectivenessEvent,
    CapabilityExecutionOutcomeEvent,
)
from personal_agent.orchestration.orchestration_contexts import ExecutiveContext
from personal_agent.orchestration.orchestration_models import RunCheckpoint, InvocationBatchState
from personal_agent.capabilities.resolver import CapabilityResolver
from personal_agent.runtime.task_runtime import next_execution_event
from personal_agent.runtime.recovery import classify_failure
from personal_agent.tools.mcp_capability import build_capability_portfolio

logger = logging.getLogger(__name__)


def _context_snapshot(state: RunCheckpoint) -> RuntimeSnapshotRef:
    if state.task_contract is None or state.task_runtime is None:
        raise RuntimeError("context projection requires task definition and runtime")
    return RuntimeSnapshotRef(
        run_id=state.run_id,
        task_id=state.task_contract.task_id,
        task_revision=state.task_contract.revision,
        runtime_revision=state.task_runtime.revision,
        event_sequence=state.task_runtime.last_event_sequence,
    )


def _append_execution_event(
    state: RunCheckpoint,
    deps: ExecutiveContext,
    event_type: str,
    *,
    goal_id: str | None = None,
    payload: dict | None = None,
) -> None:
    if state.task_runtime is None:
        raise RuntimeError("execution ledger is not initialized")
    event = next_execution_event(
        state.task_runtime,
        event_type,
        goal_id=goal_id,
        payload=payload,
    )
    state.task_runtime = deps.task_runtime_projector.project(state.task_runtime, (event,))
    state.execution_events.append(event)
    deps.control_plane_store.append_domain_event(state.run_id, event)
    state.add_event("plan_runtime_updated", {
        "execution_event": event.model_dump(mode="json"),
        "ledger_revision": state.task_runtime.revision,
    })


def _node_compile_goal_graph(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    if state.accepted_task_analysis is None:
        raise RuntimeError("goal graph compilation requires task analysis")
    compilation = deps.goal_graph_compiler.compile(
        state.accepted_task_analysis.analysis,
        state.entry_text,
    )
    state.task_contract = compilation.task_contract
    state.context_inventory = compilation.context_inventory
    state.task_runtime = TaskRuntimeProjection(
        task_id=compilation.task_contract.task_id,
        task_revision=compilation.task_contract.revision,
        goal_graph_revision=0,
    )
    _append_execution_event(state, deps, "task_created", payload={
        "task_contract": state.task_contract.model_dump(mode="json"),
    })
    for goal_id, item in compilation.runtime.goal_states.items():
        _append_execution_event(state, deps, "goal_added", goal_id=goal_id, payload={
            "runtime": item.model_dump(mode="json"),
        })
    if state.intake is None:
        raise RuntimeError("task compilation requires intake state")
    state.intake, state.task_compilation_commit = deps.task_compilation_committer.commit(
        state.intake,
        state.task_contract,
        state.task_runtime,
        expected_proposal_revision=state.intake.proposal_revision,
    )
    state.control.turn_index = 0
    state.control.proposal = None
    state.decision_admission = None
    state.decision_feedback = []
    state.control.accepted_intent = None
    state.control.resolved_command = None
    state.control.actions = []
    state.control.action_outcome = None
    state.execution_fact_reports = {}
    state.verification_reports = {}
    state.verification_feedback = {}
    state.completion_report = None
    state.final_answer_proposal = None
    state.final_answer_admission = None
    state.control.observations = []
    from personal_agent.runtime.contracts.planning import PlanRuntimeProjection, PlanningUsage
    state.planning_facts = None
    state.coordination = None
    state.planner_profile = deps.planner_profile
    state.planning_usage = PlanningUsage()
    state.plan_definition = None
    state.plan_runtime = PlanRuntimeProjection()
    state.frontier_decision = None
    state.plan_monitor_decision = None
    state.replan_request = None
    state.control.dispatch_groups = []
    state.add_event("goal_graph_compiled", {
        "task_id": state.task_contract.task_id,
        "revision": state.task_contract.revision,
        "goal_ids": [item.goal_id for item in state.goals],
    })
    return {
        "task_contract": state.task_contract,
        "intake": state.intake,
        "task_runtime": state.task_runtime,
        "task_compilation_commit": state.task_compilation_commit,
        "context_inventory": state.context_inventory,
        "context_projections": state.context_projections,
        "control": state.control,
        "active_procedure": state.active_procedure,
        "planning_facts": state.planning_facts,
        "coordination": state.coordination,
        "planner_profile": state.planner_profile,
        "planning_usage": state.planning_usage,
        "plan_definition": state.plan_definition,
        "plan_runtime": state.plan_runtime,
        "frontier_decision": state.frontier_decision,
        "execution_events": state.execution_events,
        "events": state.events,
        "answer": state.answer,
    }


def _node_project_planning_facts(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    if state.task_contract is None or state.task_runtime is None:
        raise RuntimeError("planning facts require task and goal graph")
    if state.task_compilation_commit is None:
        raise RuntimeError("planning facts require an atomic task compilation commit")
    if deps.post_task_compilation_commit_hook is not None:
        deps.post_task_compilation_commit_hook(state.run_id)
    procedures = deps.procedure_applicability_resolver.resolve(
        state.task_contract,
        state.task_runtime,
    )
    planning_items = _planning_context_items(state, procedures)
    projection = deps.context_manager.project_contract(
        planning_items,
        purpose="planning",
        budget=_context_budget(state),
        source_snapshot=_context_snapshot(state),
    )
    state.context_projections.append(projection)
    materialized = deps.context_gateway.open(
        projection, planning_items, purpose="planning",
    )
    state.add_event("context_projected", projection.model_dump(mode="json"))
    state.add_event("context_materialized", {
        "projection_id": projection.projection_id,
        "purpose": "planning",
        "materialized_refs": materialized.materialized_refs,
    })
    from personal_agent.planning.adaptive import profile_for_task

    state.planner_profile = profile_for_task(state.task_contract, procedures)
    state.planning_facts = deps.planning_fact_projector.project(
        state.task_contract,
        state.task_runtime,
        procedures,
        state.planner_profile,
    )
    state.add_event("planning_facts_projected", state.planning_facts.model_dump(mode="json"))
    return {
        "planning_facts": state.planning_facts,
        "planner_profile": state.planner_profile,
        "context_projections": state.context_projections,
        "events": state.events,
    }


def _node_assess_coordination(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    if state.planning_facts is None or state.task_runtime is None:
        raise RuntimeError("planning mode requires projected facts")
    target_goal_ids = tuple(
        item.goal_id for item in state.goals
        if item.status not in {"verified", "degraded", "abandoned"}
    )
    from personal_agent.planning.adaptive import CoordinationDecisionUnavailable

    try:
        state.coordination, state.planning_usage = deps.coordination_policy.assess(
            state.planning_facts,
            target_goal_ids=target_goal_ids,
            limits=state.planner_profile.limits,
            usage=state.planning_usage,
        )
    except CoordinationDecisionUnavailable as exc:
        state.coordination = None
        state.control.advance_phase("closed")
        state.control.disposition = "terminate"
        state.answer = _render_control_status("terminal", (str(exc),))
        state.add_event("coordination_decision_unavailable", {
            "reason_code": str(exc),
            "disposition": "terminal",
        })
        return {
            "coordination": None,
            "planning_usage": state.planning_usage,
            "control": state.control,
            "answer": state.answer,
            "events": state.events,
        }
    state.add_event("coordination_assessed", {
        **state.coordination.model_dump(mode="json"),
        "profile_id": state.planner_profile.profile_id,
        "authority": state.planner_profile.authority,
    })
    return {
        "coordination": state.coordination,
        "planning_usage": state.planning_usage,
        "events": state.events,
    }


def _node_create_or_revise_plan(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    if (
        state.task_contract is None
        or state.task_runtime is None
        or state.coordination is None
    ):
        raise RuntimeError("adaptive planning requires task, goal graph, and mode")
    procedures = deps.procedure_applicability_resolver.resolve(
        state.task_contract,
        state.task_runtime,
    )
    planning_items = _planning_context_items(state, procedures)
    projection = deps.context_manager.project_contract(
        planning_items,
        purpose="planning",
        budget=_context_budget(state),
        source_snapshot=_context_snapshot(state),
    )
    state.context_projections.append(projection)
    materialized = deps.context_gateway.open(
        projection, planning_items, purpose="planning",
    )
    coordinationl_context = materialized.model_payload()
    state.add_event("context_projected", projection.model_dump(mode="json"))
    state.add_event("context_materialized", {
        "projection_id": projection.projection_id,
        "purpose": "planning",
        "materialized_refs": materialized.materialized_refs,
    })
    replacement_reasons = {
        "task_revision_changed", "goal_graph_revision_changed",
        "planning_horizon_exhausted",
    }
    if (
        state.replan_request is not None
        and state.replan_request.reason_code in replacement_reasons
        and state.planning_usage.horizon_replacements
        >= state.planner_profile.limits.max_horizon_replacements
    ):
        state.control.advance_phase("closed")
        state.control.disposition = "terminate"
        state.add_event("adaptive_plan_replacement_budget_exhausted", {
            "request": state.replan_request.model_dump(mode="json"),
            "budget": state.planning_usage.model_dump(mode="json"),
        })
        state.replan_request = None
        return {
            "planning_usage": state.planning_usage,
            "replan_request": None,
            "control": state.control,
            "events": state.events,
        }
    if (
        state.replan_request is not None
        and state.plan_definition is not None
        and state.replan_request.reason_code not in replacement_reasons
    ):
        patch, state.planning_usage = deps.adaptive_planner.create_patch(
            state.task_contract,
            state.plan_definition,
            state.plan_runtime,
            state.replan_request,
            state.planner_profile.limits,
            state.planning_usage,
            model_context=coordinationl_context,
        )
        if patch is None:
            state.control.advance_phase("closed")
            state.control.disposition = "terminate"
            state.add_event("adaptive_plan_patch_unavailable", {
                "request": state.replan_request.model_dump(mode="json"),
            })
        else:
            from personal_agent.planning.adaptive import (
                PlanningValidationError,
                planning_rejection_feedback,
            )

            try:
                candidate_plan, candidate_ledger = deps.plan_runtime_projector.apply_patch(
                    state.plan_definition,
                    state.plan_runtime,
                    patch,
                )
                deps.plan_validator.validate(
                    candidate_plan,
                    state.task_contract,
                    state.task_runtime,
                    state.planner_profile,
                )
            except PlanningValidationError as exc:
                remaining = max(
                    state.planner_profile.limits.max_planner_calls
                    - state.planning_usage.planner_calls,
                    0,
                )
                feedback = planning_rejection_feedback(
                    state.task_contract,
                    state.task_runtime,
                    reason_code="plan_patch_invalid",
                    revision_attempt=state.planning_usage.planner_calls,
                    revision_budget_remaining=remaining,
                    disposition="revise_model" if remaining else "terminal",
                    required_repair=str(exc),
                )
                state.decision_feedback.append(feedback)
                if feedback.disposition == "revise_model":
                    state.control.disposition = "replace_plan"
                else:
                    state.control.advance_phase("closed")
                    state.control.disposition = "terminate"
                    state.replan_request = None
                state.add_event(
                    "planning_feedback_created",
                    feedback.model_dump(mode="json"),
                )
            else:
                state.plan_definition = candidate_plan
                state.plan_runtime = candidate_ledger
                state.planning_usage = state.planning_usage.model_copy(update={
                    "applied_patches": state.planning_usage.applied_patches + 1,
                })
                state.control.advance_phase("preparing_model_call")
                state.control.disposition = "continue_control"
                state.add_event("adaptive_plan_patched", patch.model_dump(mode="json"))
                state.replan_request = None
        return {
            "plan_definition": state.plan_definition,
            "plan_runtime": state.plan_runtime,
            "planning_usage": state.planning_usage,
            "replan_request": state.replan_request,
            "control": state.control,
            "decision_feedback": state.decision_feedback,
            "events": state.events,
            "context_projections": state.context_projections,
        }
    plan, state.planning_usage, planning_feedback = deps.adaptive_planner.create_plan(
        state.task_contract,
        state.task_runtime,
        state.coordination,
        procedures,
        state.planner_profile.limits,
        state.planning_usage,
        model_context=coordinationl_context,
        observation_ids=tuple(
            item.observation_id for item in state.control.observations[-6:]
        ),
        gap_ids=tuple(
            gap for item in state.goals for gap in item.evidence_gaps
        ),
    )
    if plan is None:
        if planning_feedback is None:
            raise RuntimeError("planner returned neither a plan nor DecisionFeedback")
        state.decision_feedback.append(planning_feedback)
        state.plan_definition = None
        state.plan_runtime = PlanRuntimeProjection()
        if planning_feedback.disposition == "revise_model":
            state.control.disposition = "replace_plan"
        else:
            state.control.advance_phase("closed")
            state.control.disposition = "terminate"
        state.add_event("planning_feedback_created", planning_feedback.model_dump(mode="json"))
    else:
        deps.plan_validator.validate(
            plan,
            state.task_contract,
            state.task_runtime,
            state.planner_profile,
        )
        previous_plan = state.plan_definition
        replacing = previous_plan is not None
        state.plan_definition = plan
        state.plan_runtime = (
            deps.plan_runtime_projector.replace(previous_plan, state.plan_runtime, plan)
            if replacing else deps.plan_runtime_projector.create(plan)
        )
        state.control.advance_phase("preparing_model_call")
        state.control.disposition = "continue_control"
        if replacing:
            state.planning_usage = state.planning_usage.model_copy(update={
                "horizon_replacements": state.planning_usage.horizon_replacements + 1,
            })
        state.add_event("adaptive_plan_created", {
            "plan": plan.model_dump(mode="json"),
            "replacing": replacing,
        })
    state.replan_request = None
    return {
        "plan_definition": state.plan_definition,
        "plan_runtime": state.plan_runtime,
        "planning_usage": state.planning_usage,
        "replan_request": state.replan_request,
        "control": state.control,
        "decision_feedback": state.decision_feedback,
        "events": state.events,
        "context_projections": state.context_projections,
    }


def _node_monitor_plan(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    if state.task_contract is None or state.task_runtime is None:
        raise RuntimeError("plan monitoring requires task and goal graph")
    state.control.advance_phase("monitoring")
    if state.plan_definition is not None:
        status_by_goal = {
            item.goal_id: item.status for item in state.goals
        }
        for step_id in tuple(state.selected_plan_step_ids):
            step = next(
                (item for item in state.plan_definition.steps if item.step_id == step_id),
                None,
            )
            if step is None:
                continue
            if status_by_goal.get(step.goal_id) in {"verified", "degraded"}:
                state.plan_runtime = deps.plan_runtime_projector.append(
                    state.plan_definition,
                    state.plan_runtime,
                    "step_satisfied",
                    step_ids=(step_id,),
                )
            elif state.control.observations:
                latest = state.control.observations[-1]
                if not latest.goal_id or latest.goal_id == step.goal_id:
                    state.plan_runtime = deps.plan_runtime_projector.append(
                        state.plan_definition,
                        state.plan_runtime,
                        "step_observed",
                        step_ids=(step_id,),
                        observation_ids=(latest.observation_id,),
                    )
    monitor_items = _monitor_context_items(state)
    projection = deps.context_manager.project_contract(
        monitor_items,
        purpose="plan_monitoring",
        budget=_context_budget(state),
        source_snapshot=_context_snapshot(state),
    )
    state.context_projections.append(projection)
    materialized = deps.context_gateway.open(
        projection, monitor_items, purpose="plan_monitoring",
    )
    state.plan_monitor_decision, state.plan_runtime = deps.plan_monitor.inspect(
        state.task_contract,
        state.task_runtime,
        state.plan_definition,
        state.plan_runtime,
        tuple(state.control.observations),
        state.planner_profile.limits,
        state.planning_usage,
        model_context=materialized.model_payload(),
    )
    if state.plan_monitor_decision.decision_source == "semantic":
        state.planning_usage = state.planning_usage.model_copy(update={
            "semantic_monitor_calls": state.planning_usage.semantic_monitor_calls + 1,
        })
    state.replan_request = state.plan_monitor_decision.replan_request
    if (
        state.plan_monitor_decision.impact in {"step_invalidated", "branch_invalidated"}
        and state.plan_monitor_decision.affected_step_ids
    ):
        state.plan_runtime = deps.plan_runtime_projector.append(
            state.plan_definition,
            state.plan_runtime,
            "step_invalidated",
            step_ids=state.plan_monitor_decision.affected_step_ids,
        )
    if state.plan_monitor_decision.action in {"patch", "replace"}:
        state.control.advance_phase("monitoring")
        state.control.disposition = (
            "patch_plan" if state.plan_monitor_decision.action == "patch" else "replace_plan"
        )
    elif state.plan_monitor_decision.action == "request_input":
        state.control.advance_phase("awaiting_input")
        state.control.disposition = "await_input"
    elif state.plan_monitor_decision.action == "stop":
        state.control.advance_phase("closed")
        state.control.disposition = "terminate"
    else:
        state.control.advance_phase("preparing_model_call")
        state.control.disposition = "continue_control"
    state.add_event("plan_monitored", state.plan_monitor_decision.model_dump(mode="json"))
    return {
        "plan_runtime": state.plan_runtime,
        "plan_monitor_decision": state.plan_monitor_decision,
        "replan_request": state.replan_request,
        "control": state.control,
        "planning_usage": state.planning_usage,
        "context_projections": state.context_projections,
        "events": state.events,
    }


def _node_project_control_state(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    if state.task_contract is None or state.task_runtime is None:
        raise RuntimeError("control state requires task and ledger")
    registry = build_capability_portfolio(
        tools=deps.tool_executor.list_tools(exposures={"public_agent", "scoped_agent", "admin"}),
        agents=deps.agent_gateway.profiles(),
    )
    grouped: dict[tuple[str, ...], dict[str, set[str]]] = {}
    for capability in registry.list():
        class_key = (
            capability.kind,
            capability.output_contract,
            capability.operation_scope.side_effect_class,
            capability.auth_scope,
            capability.trust_level,
            capability.freshness_profile,
            capability.evidence_contract,
            capability.data_egress_class,
            capability.failure_semantics,
        )
        bucket = grouped.setdefault(class_key, {
            "domains": set(), "resource_types": set(),
            "operations": set(), "providers": set(),
        })
        bucket["domains"].update(capability.semantic_domains)
        bucket["resource_types"].update(capability.resource_types)
        bucket["operations"].update(capability.operations)
        bucket["providers"].add(capability.provider)
    summaries = tuple(CapabilityClassSummary(
        kind=class_key[0],
        semantic_domains=tuple(sorted(values["domains"])),
        resource_types=tuple(sorted(values["resource_types"])),
        operations=tuple(sorted(values["operations"])),
        providers=tuple(sorted(values["providers"])),
        output_contract=class_key[1],
        side_effect_class=class_key[2],
        authority_scope=class_key[3],
        trust_level=class_key[4],
        freshness_profile=class_key[5],
        evidence_contract=class_key[6],
        data_egress_class=class_key[7],
        failure_semantics=class_key[8],
    ) for class_key, values in sorted(grouped.items()))
    from personal_agent.runtime.contracts.control import ControlState

    state.control.state = ControlState(
        task_id=state.task_contract.task_id,
        task_revision=state.task_contract.revision,
        task_goal=state.task_contract.user_goal,
        ledger_revision=state.task_runtime.revision,
        active_goal_ids=state.task_runtime.active_goal_ids,
        active_skill_ids=state.task_runtime.active_skill_ids,
        available_capability_classes=summaries,
        procedure_candidates=deps.procedure_applicability_resolver.resolve(
            state.task_contract,
            state.task_runtime,
        ),
        outstanding_evidence_gaps=tuple(
            gap for item in state.goals for gap in item.evidence_gaps
        ),
        pending_approval_ids=(state.control.pending_interaction.step_id,)
        if state.control.pending_interaction else (),
        latest_observations=tuple(state.control.observations[-6:]),
        remaining_provider_calls=max(
            state.task_contract.constraints.max_provider_calls - state.provider_call_count, 0,
        ),
        remaining_executive_turns=max(
            state.task_contract.constraints.max_executive_turns - state.control.turn_index, 0,
        ),
    )
    state.add_event("control_state_projected", {
        "task_id": state.control.state.task_id,
        "ledger_revision": state.control.state.ledger_revision,
        "remaining_executive_turns": state.control.state.remaining_executive_turns,
    })
    control_items = _control_context_items(state)
    projection = deps.context_manager.project_contract(
        control_items,
        purpose="executive_decision",
        budget=_context_budget(state),
        source_snapshot=_context_snapshot(state),
    )
    state.context_projections.append(projection)
    deps.context_gateway.open(
        projection, control_items, purpose="executive_decision",
    )
    state.add_event("context_projected", projection.model_dump(mode="json"))
    return {
        "control": state.control,
        "context_projections": state.context_projections,
        "events": state.events,
    }


def _node_decide(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    if state.task_contract is None or state.task_runtime is None or state.control.state is None:
        raise RuntimeError("executive decision requires projected control state")
    state.control.advance_phase("proposing")
    control_projection = next(
        (
            item for item in reversed(state.context_projections)
            if item.purpose == "executive_decision"
        ),
        None,
    )
    control_model_context = (
        deps.context_gateway.open(
            control_projection,
            _control_context_items(state),
            purpose="executive_decision",
        ).model_payload()
        if control_projection is not None else None
    )
    revision_feedback = (
        state.decision_admission.feedback
        if state.decision_admission is not None else None
    )
    previous_proposal_ref = (
        state.control.proposal.proposal_id
        if state.control.proposal is not None and revision_feedback is not None else None
    )
    prior_decision = (
        state.control.proposal.decision
        if state.control.proposal is not None and revision_feedback is not None else None
    )
    if state.control.state.remaining_executive_turns <= 0:
        proposal = deps.controller.terminal_proposal(
            state.task_contract,
            state.task_runtime,
            reason_code="executive_turn_budget_exhausted",
            user_message="任务达到最大决策轮数，运行已停止。",
        )
    else:
        state.frontier_decision = None
        capability_recovery_turn = bool(
            state.control.observations
            and state.control.observations[-1].kind == "capability_gap"
        )
        if (
            state.coordination is not None
            and state.coordination.mode == "deliberative"
            and not capability_recovery_turn
        ):
            if state.plan_definition is None:
                raise RuntimeError("deliberative control requires an active plan definition")
            frontier = deps.plan_runtime_projector.frontier(state.plan_definition, state.plan_runtime)
            if not frontier:
                proposal = deps.controller.terminal_proposal(
                    state.task_contract,
                    state.task_runtime,
                    reason_code="plan_frontier_empty",
                    user_message="当前计划没有 ready step，运行已停止。",
                )
            else:
                state.frontier_decision = deps.frontier_selector.select(
                    frontier,
                    state.planner_profile,
                )
                # A frontier is a deterministic scheduling candidate, not an
                # accepted execution fact.  Do not advance the Plan Runtime
                # until the model proposal has passed Admission; otherwise a
                # rejected proposal consumes the only ready step and the next
                # turn falsely derives ``plan_frontier_empty``.
                proposal = deps.controller.propose(
                    state.task_contract,
                    state.task_runtime,
                    observations=tuple(state.control.observations),
                    capability_classes=state.control.state.available_capability_classes,
                    control_state=state.control.state,
                    model_context=control_model_context,
                    supersedes_proposal_ref=previous_proposal_ref,
                    revision_feedback_ref=state.control.active_feedback_ref,
                    revision_attempt=state.control.revision_attempt,
                    prior_decision=prior_decision,
                    revision_scope=(revision_feedback.revision_scope if revision_feedback else None),
                )
        else:
            proposal = deps.controller.propose(
                state.task_contract,
                state.task_runtime,
                observations=tuple(state.control.observations),
                capability_classes=state.control.state.available_capability_classes,
                control_state=state.control.state,
                model_context=control_model_context,
                supersedes_proposal_ref=previous_proposal_ref,
                revision_feedback_ref=state.control.active_feedback_ref,
                revision_attempt=state.control.revision_attempt,
                prior_decision=prior_decision,
                revision_scope=(revision_feedback.revision_scope if revision_feedback else None),
            )
    state.control.turn_index += 1
    semantic_hash = proposal.intent_semantic_hash
    state.control.last_intent_semantic_hash = semantic_hash
    state.control.proposal = proposal
    state.control.last_submission_hash = state.control.proposal.submission_hash
    state.decision_admission = None
    state.control.accepted_intent = None
    state.control.resolved_command = None
    state.add_event("executive_decision", {
        "turn": state.control.turn_index,
        "proposal": proposal.model_dump(mode="json"),
        "semantic_hash": semantic_hash,
    })
    return {
        "control": state.control,
        "frontier_decision": state.frontier_decision,
        "plan_runtime": state.plan_runtime,
        "events": state.events,
    }


def _node_admit_decision(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    if state.task_contract is None or state.task_runtime is None or state.control.proposal is None:
        raise RuntimeError("decision admission requires task, runtime, and proposal")
    state.control.advance_phase("admitting")
    prior_proposal = next((
        record.proposal for record in reversed(state.decision_audit)
        if record.proposal.proposal_id == state.control.proposal.supersedes_proposal_ref
    ), None)
    revision_feedback = next((
        feedback for feedback in reversed(state.decision_feedback)
        if feedback.feedback_id == state.control.proposal.revision_feedback_ref
    ), None)
    admission = deps.decision_admission.admit(
        state.task_contract,
        state.task_runtime,
        state.control.proposal,
        state.control.state,
        prior_proposal=prior_proposal,
        revision_feedback=revision_feedback,
    )
    state.decision_admission = admission
    audit = DecisionAuditRecord(
        run_id=state.run_id,
        turn_ref=state.control.turn_id,
        proposal=state.control.proposal,
        admission=admission,
    )
    state.decision_audit.append(audit)
    deps.control_plane_store.append_decision_audit(audit)
    if admission.verdict == "accepted":
        state.control.accepted_intent = deps.accepted_intent_compiler.compile(
            state.task_contract,
            state.task_runtime,
            state.control.proposal,
            admission,
        )
        state.control.resolved_command = deps.execution_command_resolver.resolve(
            state.task_contract,
            state.control.accepted_intent,
            mandatory_procedure=next((
                item for item in (state.control.state.procedure_candidates if state.control.state else ())
                if item.goal_id == state.control.accepted_intent.goal_id
                and item.status == "mandatory"
            ), None),
        )
        deps.control_plane_store.put_command(state.run_id, state.control.resolved_command)
        state.control_commits.append(deps.control_committer.commit(
            state.control,
            state.task_runtime,
            admission_ref=admission.admission_id,
            admission_verdict=admission.verdict,
            admission_proposal_ref=admission.proposal_ref,
            expected_task_revision=state.task_contract.revision,
            expected_event_cursor=state.task_runtime.last_event_sequence,
        ))
        state.add_event("decision_admitted", {
            "turn": state.control.turn_index,
            "proposal_ref": state.control.proposal.proposal_id,
            "admission": admission.model_dump(mode="json"),
            "accepted_intent_ref": state.control.accepted_intent.accepted_intent_id,
            "command_ref": state.control.resolved_command.command_id,
            "authorization_digest": state.control.resolved_command.authorization_digest,
            "execution_command_digest": state.control.resolved_command.execution_command_digest,
        })
        _append_execution_event(state, deps, "accepted_intent_created", payload={
            "accepted_intent": state.control.accepted_intent.model_dump(mode="json"),
        })
        _append_execution_event(state, deps, "execution_command_resolved", payload={
            "resolved_command": state.control.resolved_command.model_dump(mode="json"),
        })
        if state.plan_definition is not None and state.frontier_decision is not None:
            state.plan_runtime = deps.plan_runtime_projector.append(
                state.plan_definition,
                state.plan_runtime,
                "frontier_selected",
                step_ids=state.frontier_decision.selected_step_ids,
                payload={"decision": state.frontier_decision.model_dump(mode="json")},
            )
        state.control.active_feedback_ref = None
        state.control.revision_attempt = 0
    else:
        state.control.accepted_intent = None
        state.control.resolved_command = None
        state.add_event("decision_rejected", {
            "turn": state.control.turn_index,
            "proposal_ref": state.control.proposal.proposal_id,
            "admission": admission.model_dump(mode="json"),
        })
    return {
        "control": state.control,
        "decision_admission": state.decision_admission,
        "decision_audit": state.decision_audit,
        "control_commits": state.control_commits,
        "plan_runtime": state.plan_runtime,
        "task_runtime": state.task_runtime,
        "execution_events": state.execution_events,
        "events": state.events,
    }


def _node_admit_execution_route(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    intent = state.control.accepted_intent
    command = state.control.resolved_command
    if intent is None or command is None:
        raise RuntimeError("route admission requires an accepted control decision")
    state.control.advance_phase("routing")
    decision = intent.decision
    if command.procedure_invocation is not None and not isinstance(decision, InvokeProcedureDecision):
        decision = InvokeProcedureDecision(
            target_goal_id=decision.target_goal_id,
            basis=decision.basis,
            expected_progress=decision.expected_progress,
            procedure_invocation=command.procedure_invocation,
        )
    if not isinstance(decision, (ExecuteBoundedActionDecision, DelegateDecision, InvokeProcedureDecision)):
        state.control.execution_route_decision = None
        return {"control": state.control}
    proposal = deps.route_policy.propose(decision)
    state.control.execution_route_decision = deps.route_policy.admit(
        proposal,
        decision,
        state.control.state,
    )
    if state.control.execution_route_decision.accepted_route != command.route:
        raise RuntimeError("route admission disagrees with the immutable execution command")
    state.add_event("execution_route_admitted", {
        "proposal": proposal.model_dump(mode="json"),
        "decision": state.control.execution_route_decision.model_dump(mode="json"),
    })
    return {"control": state.control, "events": state.events}


def _node_handle_decision_denial(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    admission = state.decision_admission
    if admission is None or admission.verdict == "accepted":
        raise RuntimeError("decision denial handler requires a rejected admission")
    feedback = admission.feedback
    if feedback is None:
        raise RuntimeError("non-accepted admission must include DecisionFeedback")
    state.control.active_feedback_ref = feedback.feedback_id
    state.decision_feedback.append(feedback)
    cycle_key = canonical_digest({
        "task_revision": admission.snapshot.task_revision,
        "stage": feedback.stage,
        "reason_codes": feedback.reason_codes,
        "rejection_equivalence_hash": feedback.rejection_equivalence_hash,
        "governance_snapshot_ref": feedback.governance_snapshot_ref,
        "upstream_intent_hash": state.control.last_intent_semantic_hash,
    })
    repeated = cycle_key in state.control.seen_decision_cycle_keys
    state.control.seen_decision_cycle_keys = (*state.control.seen_decision_cycle_keys, cycle_key)[-32:]
    if repeated:
        state.control.cross_stage_revision_cycles += 1
    disposition = feedback.disposition
    if (
        disposition == "revise_model"
        and feedback.revision_budget_remaining > 0
        and state.control.cross_stage_revision_cycles < state.task_contract.constraints.revision_budget
    ):
        state.control.revision_attempt += 1
        state.control.advance_phase("preparing_model_call")
        state.control.disposition = "continue_control"
        state.add_event("decision_feedback_created", feedback.model_dump(mode="json"))
    elif disposition == "request_external_input":
        from personal_agent.kernel.contracts.interaction import InteractionRequest

        state.control.pending_interaction = InteractionRequest(
            kind="clarification_required",
            action_type="decision_revision",
            step_id=feedback.feedback_id,
            title="需要外部输入",
            message=feedback.reason_codes[0],
            missing_information=feedback.required_repairs,
        )
        state.control.advance_phase("awaiting_input")
        state.control.disposition = "await_input"
        state.add_event("decision_feedback_external_input_required", feedback.model_dump(mode="json"))
    elif disposition == "request_capability_acquisition":
        state.control.advance_phase("awaiting_input")
        state.control.disposition = "pause"
        state.add_event("decision_feedback_capability_acquisition_required", feedback.model_dump(mode="json"))
    elif disposition == "await_environment_change":
        state.control.advance_phase("awaiting_input")
        state.control.disposition = "pause"
        state.add_event("decision_feedback_environment_wait", feedback.model_dump(mode="json"))
    else:
        state.control.advance_phase("closed")
        state.control.disposition = "terminate"
        state.answer = _render_control_status("terminal", feedback.reason_codes)
        _append_execution_event(state, deps, "task_terminated", payload={
            "reason": "policy_denied",
            "reason_code": feedback.reason_codes[0],
            "admission_ref": admission.admission_id,
        })
    return {
        "answer": state.answer,
        "control": state.control,
        "decision_feedback": state.decision_feedback,
        "task_runtime": state.task_runtime,
        "task_compilation_commit": state.task_compilation_commit,
        "execution_events": state.execution_events,
        "events": state.events,
    }


def _after_decision_admission(state: RunCheckpoint) -> str:
    admission = state.decision_admission
    return "route" if admission is not None and admission.verdict == "accepted" else "feedback"


def _after_decision_feedback(state: RunCheckpoint) -> str:
    return "revise" if state.control.disposition == "continue_control" else "stop"


def _node_apply_decision(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    intent = state.control.accepted_intent
    command = state.control.resolved_command
    if intent is None or command is None or state.task_runtime is None or state.task_contract is None:
        raise RuntimeError("cannot apply an empty executive decision")
    decision = intent.decision
    if command.procedure_invocation is not None and not isinstance(decision, InvokeProcedureDecision):
        decision = InvokeProcedureDecision(
            target_goal_id=decision.target_goal_id,
            basis=decision.basis,
            expected_progress=decision.expected_progress,
            procedure_invocation=command.procedure_invocation,
        )
    state.control.actions = []
    state.control.action_outcome = None
    state.invocation_batch = InvocationBatchState()

    if isinstance(decision, ExecuteBoundedActionDecision):
        state.control.actions = [decision.bounded_action]
        if state.selected_plan_step_ids and state.plan_definition is not None:
            state.plan_runtime = deps.plan_runtime_projector.append(
                state.plan_definition,
                state.plan_runtime,
                "step_running",
                step_ids=tuple(state.selected_plan_step_ids),
            )
        steps = _steps_for_action(state, decision.bounded_action)
        state.invocation_batch = InvocationBatchState(
            invocations=list(steps),
        )
        state.add_event("action_materialized", {
            "action": state.current_action.model_dump(mode="json"),
            "step_count": len(steps),
        })
        update = _route_update(state, "action")
        update["plan_runtime"] = state.plan_runtime
        return update

    if isinstance(decision, DelegateDecision):
        action, step, gap = _materialize_delegate(state, deps, decision)
        if gap is not None:
            state.control.observations.append(gap)
            _append_execution_event(state, deps, "goal_blocked", goal_id=decision.target_goal_id, payload={
                "evidence_gaps": (gap.requirement_id,),
            })
            state.add_event("capability_gap", gap.model_dump(mode="json"))
            return _route_update(state, "loop")
        state.control.actions = [action]
        state.invocation_batch = InvocationBatchState(invocations=[step])
        state.add_event("action_materialized", {
            "action": action.model_dump(mode="json"),
            "step_count": 1,
        })
        return _route_update(state, "action")

    if isinstance(decision, InvokeProcedureDecision):
        materialized = deps.procedure_runtime.start(
            decision.procedure_invocation,
        )
        procedure_grant = deps.procedure_grant_issuer.issue_start(
            state.task_contract,
            decision.procedure_invocation,
            materialized.projection,
            materialized.definition,
            command,
        )
        state.execution_grants[procedure_grant.grant_id] = procedure_grant
        procedure_action = BoundedAction(
            action_id=decision.procedure_invocation.invocation_id,
            goal_id=decision.target_goal_id,
            execution_intent="commit" if state.task_contract.mutation_intent else "acquire",
            description=f"procedure:{decision.procedure_invocation.procedure.procedure_id}",
            output_contract="ProcedureOutcome",
            proposed_resource_access=ProposedResourceAccessPlan(
                side_effect_class="procedure",
                authority_scope="procedure:execute",
                data_egress_class="content",
                trust_floor="scoped",
                freshness_contract="current_command_snapshot",
                evidence_contract="MutationReceipt",
                failure_semantics="fail_closed",
                write_set=({
                    "semantic_domain": "procedure",
                    "locator": decision.procedure_invocation.procedure.procedure_id,
                },),
            ),
            input=ProcedureActionInput(
                procedure_id=decision.procedure_invocation.procedure.procedure_id,
                procedure_run_id=materialized.projection.procedure_run_id,
                procedure_grant_ref=procedure_grant.grant_id,
            ),
        )
        state.control.actions = [procedure_action]
        state.active_procedure = materialized.projection
        state.invocation_batch = InvocationBatchState(
            invocations=list(materialized.steps),
        )
        state.add_event("procedure_started", {
            "procedure_invocation": decision.procedure_invocation.model_dump(mode="json"),
            "procedure_run_id": materialized.projection.procedure_run_id,
            "procedure_grant_ref": procedure_grant.grant_id,
            "step_count": len(materialized.steps),
        })
        return _route_update(state, "action")

    if isinstance(decision, ClarifyDecision):
        response = interrupt({
            "kind": "clarification",
            "question": decision.question,
            "task_id": state.task_contract.task_id,
        })
        observation = ObservationRef(
            goal_id=decision.target_goal_id,
            kind="user_clarification",
            provenance=observation_provenance("user", "user", str(response)),
            trust="scoped",
            summary=str(response),
            payload={"response": response},
        )
        state.control.observations.append(observation)
        return _route_update(state, "loop")

    if isinstance(decision, RequestConfirmationDecision):
        # Persist the request before pausing.  State mutations made in an
        # interrupting node are not durable until a node boundary is crossed.
        state.control.pending_interaction = InteractionRequest(
            kind="confirmation_required",
            action_type="request_confirmation",
            step_id=command.command_id,
            title=decision.title,
            message="此操作需要您的确认。",
            summary=decision.summary,
            authorization_digest=command.authorization_digest,
        )
        state.control.advance_phase("awaiting_input")
        state.control.disposition = "await_input"
        state.add_event("confirmation_required", {
            "interaction": state.control.pending_interaction.model_dump(mode="json"),
            "task_id": state.task_contract.task_id,
        })
        return {"control": state.control, "events": state.events}

    if isinstance(decision, RequestCapabilityAcquisitionDecision):
        request = CapabilityAcquisitionRequest(
            request_id=sha256(
                f"{state.task_contract.task_id}:{decision.target_goal_id}:"
                f"{decision.requirement.requirement_id}".encode()
            ).hexdigest()[:16],
            task_id=state.task_contract.task_id,
            goal_id=decision.target_goal_id,
            requirement=decision.requirement,
            method=decision.allowed_methods[0],
        )
        state.capability_acquisition = deps.capability_acquisition_manager.submit(
            state.capability_acquisition,
            request,
        )
        state.control.pending_interaction = InteractionRequest(
            kind="capability_acquisition_required",
            action_type="request_capability_acquisition",
            step_id=request.request_id,
            title="需要补充执行能力",
            message="需要用户批准能力获取请求。",
            summary=decision.requirement.purpose,
            resource_id=request.request_id,
        )
        state.control.advance_phase("awaiting_input")
        state.control.disposition = "await_input"
        state.add_event("capability_acquisition_requested", {
            "request_id": request.request_id,
            "method": request.method,
        })
        return {
            "capability_acquisition": state.capability_acquisition,
            "control": state.control,
            "events": state.events,
        }

    if isinstance(decision, FinishDecision):
        return _route_update(state, "completion")

    if isinstance(decision, TerminateDecision):
        state.answer = state.answer or decision.user_message
        _append_execution_event(state, deps, "task_terminated", payload={
            "reason": decision.reason,
            "reason_code": decision.reason_code,
        })
        return _route_update(state, "stop")

    raise RuntimeError(f"unsupported executive decision: {decision.action}")


def _node_resolve_action(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    if state.task_contract is None or state.task_runtime is None or not state.control.actions:
        raise RuntimeError("action resolution requires materialized actions")
    state.control.advance_phase("resolving_execution")
    projection = deps.context_manager.project_contract(
        _context_items(state),
        purpose="action_execution",
        budget=_context_budget(state),
        source_snapshot=_context_snapshot(state),
    )
    state.context_projections.append(projection)
    registry = build_capability_portfolio(
        tools=deps.tool_executor.list_tools(exposures={"public_agent", "scoped_agent", "admin"}),
        agents=deps.agent_gateway.profiles(),
    )
    procedure_registry = None
    resolved: list[tuple[
        BoundedAction,
        ExecutionCapabilityRequest | None,
        ExecutionResolutionResult | None,
        list[ExecutableInvocation],
    ]] = []
    for action in state.control.actions:
        request = None
        resolution = None
        if action.requirement is not None and action.requirement.operations:
            request = ExecutionCapabilityRequest(
                task_id=state.task_contract.task_id,
                task_revision=state.task_contract.revision,
                goal_id=action.goal_id,
                action_id=action.action_id,
                execution_intent=action.execution_intent,
                allowed_kinds=("agent",) if "delegate" in action.requirement.operations else (
                    "local_tool", "mcp_tool", "retriever",
                ),
                allowed_operations=action.requirement.operations,
                requirements=(action.requirement,),
                policy=CapabilitySelectionPolicy(
                    read_only=action.proposed_resource_access.side_effect_class == "none",
                ),
                runtime_context=CapabilityRuntimeContext(
                    expected_local_names=(
                        (action.input.agent_id,)
                        if isinstance(action.input, DelegateActionInput) else ()
                    ),
                    resource_locator=action.requirement.resource_locator,
                    user_id=state.user_id,
                    session_id=state.session_id,
                    source_platform=(
                        state.entry_input.source_platform
                        if state.entry_input is not None else None
                    ),
                    equivalence_class=CapabilityEquivalenceClass(
                        required_output_contract=action.requirement.output_contract,
                        allowed_side_effect_class=action.proposed_resource_access.side_effect_class,
                        authority_scope=action.proposed_resource_access.authority_scope,
                        trust_floor=action.proposed_resource_access.trust_floor,
                        freshness_contract=action.proposed_resource_access.freshness_contract,
                        evidence_contract=action.proposed_resource_access.evidence_contract,
                        data_egress_class=action.proposed_resource_access.data_egress_class,
                        failure_semantics=action.proposed_resource_access.failure_semantics,
                    ),
                ),
            )
            resolution = CapabilityResolver(
                registry,
                policy_engine=deps.policy_engine,
                ranker=deps.capability_ranker,
            ).resolve(request)
            if resolution.selected_definition is None:
                coverage = resolution.coverage[0] if resolution.coverage else None
                summary = coverage.rationale if coverage is not None else "no executable capability available"
                gap = CapabilityGapObservation(
                    goal_id=action.goal_id,
                    provenance=observation_provenance(
                        "runtime", "capability_resolver", summary,
                    ),
                    trust="trusted",
                    taint=frozenset({"derived"}),
                    summary=summary,
                    requirement_id=action.requirement.requirement_id,
                    status=coverage.status if coverage is not None else "unavailable",
                    satisfied_operations=(
                        tuple(
                            operation for operation in action.requirement.operations
                            if operation not in coverage.missing_operations
                        ) if coverage else ()
                    ),
                    missing_operations=(coverage.missing_operations if coverage else action.requirement.operations),
                    attempted_capability_classes=tuple(action.requirement.semantic_domains),
                    suggested_capability_classes=("mcp_tool", "agent"),
                )
                state.control.observations.append(gap)
                state.add_event("capability_gap", gap.model_dump(mode="json"))
                state.control.resolved_actions = []
                # The capability resolver produced a typed accepted result.
                # Deliberative control sends it to plan monitoring; reactive
                # control has no monitor node, so close the acceptance boundary
                # before the graph re-enters model preparation.
                state.control.advance_phase("accepting_result")
                if state.plan_definition is None:
                    state.control.advance_phase("preparing_model_call")
                state.control.disposition = "continue_control"
                return {
                    "control": state.control,
                    "context_projections": state.context_projections,
                    "invocation_batch": state.invocation_batch,
                    "execution_grants": state.execution_grants,
                    "events": state.events,
                }
        matching_steps = [
            step for step in state.invocation_batch.invocations
            if step.step_id == action.action_id or step.goal_id == action.goal_id
        ]
        resolved.append((action, request, resolution, matching_steps))

    selected_bindings = tuple(sorted({
        f"{item.selected_definition.provider}:"
        f"{item.selected_definition.local_name or item.selected_definition.capability_id}"
        for _, _, item, _ in resolved
        if item is not None and item.selected_definition is not None
    }))
    if selected_bindings:
        prior_command = state.control.resolved_command
        accepted_intent = state.control.accepted_intent
        if prior_command is None or accepted_intent is None:
            raise RuntimeError("provider binding requires an accepted command lineage")
        state.control.resolved_command = deps.execution_command_resolver.resolve(
            state.task_contract,
            accepted_intent,
            provider_binding_refs=selected_bindings,
            provider_binding_derivations=tuple(
                item.decision.derivation_record
                for _, _, item, _ in resolved
                if item is not None and item.selected_definition is not None
            ),
            supersedes_command_ref=prior_command.command_id,
        )
        deps.control_plane_store.put_command(state.run_id, state.control.resolved_command)
        _append_execution_event(state, deps, "execution_command_resolved", payload={
            "resolved_command": state.control.resolved_command.model_dump(mode="json"),
        })
        state.add_event("provider_bound_command_resolved", {
            "command_ref": state.control.resolved_command.command_id,
            "supersedes_command_ref": prior_command.command_id,
            "provider_binding_refs": selected_bindings,
            "authorization_digest": state.control.resolved_command.authorization_digest,
            "execution_command_digest": state.control.resolved_command.execution_command_digest,
        })

    specs = []
    for action, request, resolution, matching_steps in resolved:
        grant = None
        if request is not None and resolution is not None:
            selected = resolution.selected_definition
            if selected is None or state.control.resolved_command is None:
                raise RuntimeError("selected capability requires a provider-bound command")
            grant = deps.capability_grant_issuer.issue(
                request,
                selected,
                state.control.resolved_command,
            )
            state.execution_grants[grant.grant_id] = grant
        access = deps.resource_access_resolver.resolve(
            action.proposed_resource_access,
            runtime_preflight=action.proposed_resource_access,
            preflight_complete=(
                action.proposed_resource_access.side_effect_class == "none"
                or bool(action.proposed_resource_access.write_set)
            ),
        )
        spec = deps.action_builder.build(
            decision_ref=state.control.resolved_command.command_id,
            action=action,
            context_projection_ref=projection.projection_id,
            access_plan=access,
            execution_grant_ref=grant.grant_id if grant is not None else None,
            retry_directive=state.control.retry_directive,
        )
        procedure_grant_ref = (
            action.input.procedure_grant_ref
            if isinstance(action.input, ProcedureActionInput) else ""
        )
        if procedure_grant_ref:
            parent_grant = state.execution_grants.get(procedure_grant_ref)
            if not isinstance(parent_grant, ProcedureGrant) or state.active_procedure is None:
                raise RuntimeError("procedure action requires its exact ProcedureGrant")
            spec = spec.model_copy(update={"execution_grant_ref": procedure_grant_ref})
            if procedure_registry is None:
                # Workflow-only handlers are not exposed to open model actions,
                # but a governed ProcedureGrant may resolve its declared nodes.
                procedure_registry = build_capability_portfolio(
                    tools=deps.tool_executor.list_tools(exposures={
                        "public_agent",
                        "scoped_agent",
                        "workflow_activity",
                        "admin",
                    }),
                    agents=deps.agent_gateway.profiles(),
                )
            _resolve_procedure_nodes(
                state,
                deps,
                portfolio=procedure_registry,
                parent_grant=parent_grant,
                steps=matching_steps,
            )
        deps.scheduler.validate_dispatch(spec)
        specs.append(spec)
        if resolution is not None:
            selected = resolution.selected_definition
            selected_name = (
                str(selected.local_name or selected.capability_id) if selected is not None else ""
            )
            state.add_event("capability_resolution", {
                "resolution_id": resolution.decision.resolution_id,
                "request_id": resolution.decision.request_id,
                "goal_id": action.goal_id,
                "action_id": action.action_id,
                "step_id": matching_steps[0].step_id if matching_steps else action.action_id,
                "execution_grant_ref": grant.grant_id if grant is not None else None,
                "selected_capability_ref": selected.capability_id if selected else None,
                "coverage": [item.model_dump(mode="json") for item in resolution.coverage],
            })
            for step in matching_steps:
                step.execution_grant_ref = grant.grant_id if grant is not None else None
                step.allowed_tools = (
                    [selected_name]
                    if selected is not None and selected.kind in {"local_tool", "mcp_tool"}
                    else []
                )
                if (
                    selected is not None
                    and step.execution_mode != "react"
                    and action.execution_intent != "commit"
                ):
                    # Decision ownership: the accepted Action owns why the
                    # capability is invoked (for example ``verify``).  Once a
                    # provider kind is bound, its graph execution shape is a
                    # closed-world mechanical projection of that binding.
                    step.action_type = {
                        "local_tool": "tool_call",
                        "mcp_tool": "tool_call",
                        "retriever": "retrieve",
                        "agent": "agent_call",
                    }[selected.kind]
                if (
                    step.execution_mode != "react"
                    and step.action_type == "tool_call"
                    and not step.tool_name
                    and step.allowed_tools
                ):
                    step.tool_name = step.allowed_tools[0]
                if selected is not None and selected.kind == "agent" and not step.agent_id:
                    step.agent_id = selected_name
    state.control.resolved_actions = specs
    state.control.dispatch_groups = list(deps.scheduler.create_dispatch_groups(
        tuple(specs),
        requested_join_policy=(
            state.frontier_decision.requested_join_policy
            if state.frontier_decision is not None else "all"
        ),
    ))
    state.control.advance_phase("preparing_dispatch")
    if state.plan_definition is not None and state.selected_plan_step_ids:
        state.plan_runtime = deps.plan_runtime_projector.append(
            state.plan_definition,
            state.plan_runtime,
            "dispatch_grouped",
            step_ids=tuple(state.selected_plan_step_ids),
            payload={
                "dispatch_groups": [
                    item.model_dump(mode="json") for item in state.control.dispatch_groups
                ],
            },
        )
    state.add_event("action_resolved", {
        "action_specs": [item.model_dump(mode="json") for item in specs],
        "context_projection": projection.model_dump(mode="json"),
    })
    return {
        "control": state.control,
        "plan_runtime": state.plan_runtime,
        "task_runtime": state.task_runtime,
        "execution_events": state.execution_events,
        "context_projections": state.context_projections,
        "invocation_batch": state.invocation_batch,
        "execution_grants": state.execution_grants,
        "active_procedure": state.active_procedure,
        "events": state.events,
    }


def _after_action_resolution(state: RunCheckpoint) -> str:
    if state.control.resolved_actions:
        return "dispatch"
    if (
        state.plan_definition is not None
        and state.control.observations
        and state.control.observations[-1].kind in {"capability_gap", "verification_gap"}
    ):
        return "monitor"
    return "control"


def _resolve_procedure_nodes(
    state: RunCheckpoint,
    deps: ExecutiveContext,
    *,
    portfolio,
    parent_grant: ProcedureGrant,
    steps: list[ExecutableInvocation],
) -> None:
    if state.task_contract is None or state.active_procedure is None:
        raise RuntimeError("procedure-node resolution requires task and procedure runtime")
    for step in steps:
        if step.action_type not in {"tool_call", "retrieve"}:
            continue
        requirement = step.capability_requirements[0] if step.capability_requirements else None
        expected_names = (step.tool_name,) if step.tool_name else ()
        definition = portfolio.get_by_name(step.tool_name) if step.tool_name else None
        if requirement is None and step.tool_name:
            if definition is None:
                raise RuntimeError(f"procedure tool has no capability definition: {step.tool_name}")
            requirement = CapabilityRequirement.from_dimensions(
                requirement_id=f"{state.active_procedure.procedure_run_id}:{step.step_id}",
                purpose=step.description,
                semantic_domains=definition.semantic_domains,
                resource_types=definition.resource_types,
                operations=definition.operations,
                output_contract=step.output_contract,
            )
            step.capability_requirements = [requirement]
        if requirement is None:
            continue
        if definition is None:
            raise RuntimeError(
                f"procedure node requires an explicit capability contract: {step.step_id}"
            )
        request = ExecutionCapabilityRequest(
            task_id=state.task_contract.task_id,
            task_revision=state.task_contract.revision,
            goal_id=step.goal_id or parent_grant.action_ref,
            action_id=step.step_id,
            execution_route_decision_ref=parent_grant.grant_id,
            execution_intent=step.execution_intent,
            allowed_kinds=("local_tool", "mcp_tool", "retriever"),
            allowed_operations=requirement.operations,
            requirements=(requirement,),
            policy=CapabilitySelectionPolicy(read_only=step.execution_intent != "commit"),
            parent_grant_ref=parent_grant.grant_id,
            runtime_context=CapabilityRuntimeContext(
                expected_local_names=expected_names,
                equivalence_class=CapabilityEquivalenceClass(
                    required_output_contract=definition.output_contract,
                    allowed_side_effect_class=definition.operation_scope.side_effect_class,
                    authority_scope=definition.auth_scope,
                    trust_floor=requirement.minimum_trust_level,
                    freshness_contract="fresh" if requirement.freshness_required else "current",
                    evidence_contract=definition.evidence_contract,
                    data_egress_class=definition.data_egress_class,
                    failure_semantics=definition.failure_semantics,
                ),
            ),
        )
        resolution = CapabilityResolver(
            portfolio,
            policy_engine=deps.policy_engine,
            ranker=deps.capability_ranker,
        ).resolve(request)
        selected = resolution.selected_definition
        if selected is None:
            raise RuntimeError(f"procedure node capability unavailable: {step.step_id}")
        accepted_intent = state.control.accepted_intent
        prior_command = state.control.resolved_command
        if accepted_intent is None or prior_command is None:
            raise RuntimeError("procedure node provider binding requires a command lineage")
        provider_binding_ref = f"{selected.provider}:{selected.local_name or selected.capability_id}"
        node_command = deps.execution_command_resolver.resolve(
            state.task_contract,
            accepted_intent,
            provider_binding_refs=(provider_binding_ref,),
            provider_binding_derivations=(resolution.decision.derivation_record,),
            supersedes_command_ref=prior_command.command_id,
        )
        deps.control_plane_store.put_command(state.run_id, node_command)
        state.control.resolved_command = node_command
        _append_execution_event(state, deps, "execution_command_resolved", payload={
            "resolved_command": node_command.model_dump(mode="json"),
            "procedure_node_id": step.procedure_node_id or step.step_id,
        })
        atomic_grant = deps.capability_grant_issuer.issue(request, selected, node_command)
        if not isinstance(atomic_grant, AtomicCapabilityGrant):
            raise RuntimeError(f"procedure node did not resolve an atomic capability: {step.step_id}")
        node_grant = deps.procedure_grant_issuer.derive_node(
            parent_grant,
            state.active_procedure,
            step,
            atomic_grant,
            node_command,
        )
        state.execution_grants[node_grant.grant_id] = node_grant
        step.execution_grant_ref = node_grant.grant_id
        if selected is not None and selected.kind in {"local_tool", "mcp_tool"}:
            selected_name = str(selected.local_name or selected.capability_id)
            step.allowed_tools = [selected_name]
            if not step.tool_name:
                step.tool_name = selected_name
        state.add_event("procedure_node_capability_resolved", {
            "procedure_run_id": state.active_procedure.procedure_run_id,
            "node_id": step.procedure_node_id or step.step_id,
            "procedure_node_grant_ref": node_grant.grant_id,
            "capability_ref": node_grant.capability_ref,
            "command_ref": node_command.command_id,
            "execution_command_digest": node_command.execution_command_digest,
        })


def _node_observe_action(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    if state.current_action is None or state.task_runtime is None:
        return _route_update(state, "loop")
    state.control.advance_phase("accepting_result")
    state.control.disposition = "continue_control"
    state.control.retry_directive = None
    statuses = [step.status for step in state.invocation_batch.invocations]
    failed = next((step for step in state.invocation_batch.invocations if step.status == "failed"), None)
    if failed is not None:
        summary = failed.failure_reason or "bounded action failed"
        if state.active_procedure is not None:
            state.active_procedure = state.active_procedure.model_copy(update={
                "status": "failed",
            })
        classification = classify_failure(summary)
        goal = next(
            (item for item in state.goals if item.goal_id == state.current_action.goal_id),
            None,
        )
        incomplete = tuple(
            item for item in (goal.coverage if goal is not None else ())
            if item.status != "satisfied"
        )
        if incomplete:
            first = incomplete[0]
            observation = CapabilityGapObservation(
                goal_id=state.current_action.goal_id,
                provenance=observation_provenance(
                    "runtime", "capability_resolver", first.rationale or summary,
                ),
                trust="trusted",
                taint=frozenset({"derived"}),
                summary=first.rationale or summary,
                requirement_id=first.requirement_id,
                status=first.status,
                missing_operations=tuple(first.missing_operations),
                attempted_capability_classes=(
                    state.current_action.requirement.purpose
                    if state.current_action.requirement else "unknown",
                ),
                resolvable_by_resource_binding=not first.resource_bound,
                resolvable_by_authorization=classification.error_code == "authorization_required",
                suggested_capability_classes=("mcp_tool", "agent"),
                payload={
                    "execution_intent": state.current_action.execution_intent,
                    "retryable": False,
                    "error_code": "capability_gap",
                    "resolvable_by_resource_binding": not first.resource_bound,
                    "resolvable_by_authorization": classification.error_code == "authorization_required",
                },
            )
            state.add_event("capability_gap", observation.model_dump(mode="json"))
        elif (
            isinstance(state.current_action.input, ProcedureActionInput)
            and failed.procedure_recovery_policy == "clarify"
        ):
            observation = ObservationRef(
                goal_id=state.current_action.goal_id,
                kind="procedure_clarification",
                provenance=observation_provenance(
                    "runtime",
                    state.current_action.input.procedure_id,
                    summary,
                ),
                trust="scoped",
                taint=frozenset({"derived"}),
                summary=summary,
                payload={
                    "procedure_id": state.current_action.input.procedure_id,
                    "procedure_node_id": failed.procedure_node_id,
                    "recovery_policy": failed.procedure_recovery_policy,
                },
            )
        else:
            observation = deps.observation_normalizer.normalize(
                goal_id=state.current_action.goal_id,
                provenance="executor",
                summary=summary,
                payload={
                    "action_id": state.current_action.action_id,
                    "step_id": failed.step_id,
                    "execution_intent": state.current_action.execution_intent,
                },
            )
        state.control.observations.append(observation)
        outcome = ActionOutcome(
            action_id=state.current_action.action_id,
            goal_id=state.current_action.goal_id,
            status="failed",
            output_contract=state.current_action.output_contract,
            observation=observation,
            error_code="capability_gap" if incomplete else classification.error_code,
            retryable=False if incomplete else classification.retryable,
            provider_calls=state.provider_call_count,
        )
        _append_execution_event(state, deps, "attempt_recorded", goal_id=state.current_action.goal_id, payload={
            "attempt": AttemptRef(
                action_id=state.current_action.action_id,
                execution_intent=state.current_action.execution_intent,
                status="failed",
            ).model_dump(mode="json"),
        })
        _record_execution_outcomes(state, deps, outcome="failed")
        attempt_count = 1 + sum(
            item.execution_intent == state.current_action.execution_intent
            for item in (goal.attempts if goal is not None else ())
        )
        state.control.retry_directive = deps.recovery_policy.directive(
            observation,
            requirement_id=(
                state.current_action.requirement.requirement_id
                if state.current_action.requirement else state.current_action.action_id
            ),
            idempotency_key=f"{state.task_contract.task_id}:{state.current_action.action_id}:{attempt_count}",
            attempt_count=attempt_count,
            max_attempts=2,
            action_idempotent=(
                state.current_action.proposed_resource_access.side_effect_class == "none"
            ),
            failed_provider_id=str(observation.payload.get("provider_id", "")),
        )
        if state.control.retry_directive.retry_kind != "none":
            failed.status = "planned"
            state.control.advance_phase("resolving_execution")
            state.control.disposition = "retry_invocation"
            state.add_event("retry_directive_issued", state.control.retry_directive.model_dump(mode="json"))
        else:
            _append_execution_event(state, deps, "goal_blocked", goal_id=state.current_action.goal_id, payload={
                "evidence_gaps": tuple(
                    f"{item.requirement_id}: {item.rationale}" for item in incomplete
                ) or (classification.error_code,),
            })
            state.control.advance_phase("accepting_result")
            state.control.disposition = "continue_control"
        if isinstance(state.current_action.input, ProcedureActionInput):
            state.add_event("procedure_failed", {
                "procedure_id": state.current_action.input.procedure_id,
                "procedure_run_id": state.current_action.input.procedure_run_id,
                "procedure_node_id": failed.procedure_node_id,
                "recovery_policy": failed.procedure_recovery_policy,
                "error": summary,
            })
        state.errors = []
    elif state.control.pending_interaction is not None or any(status == "awaiting_confirmation" for status in statuses):
        if state.active_procedure is not None:
            state.active_procedure = state.active_procedure.model_copy(update={
                "status": "awaiting_confirmation",
            })
        outcome = ActionOutcome(
            action_id=state.current_action.action_id,
            goal_id=state.current_action.goal_id,
            status="awaiting_input",
            output_contract=state.current_action.output_contract,
        )
    else:
        if state.active_procedure is not None:
            state.active_procedure = state.active_procedure.model_copy(update={
                "status": "completed",
            })
        result_keys = tuple(
            step.output_artifact_id for step in state.invocation_batch.invocations if step.output_artifact_id
        )
        action_summary = _action_summary(state)
        action_step_ids = {
            step.step_id for step in state.invocation_batch.invocations
        }
        carries_instruction_taint = any(
            "instruction" in item.taint
            and str(item.payload.get("step_id") or "") in action_step_ids
            for item in state.context_inventory.items.values()
        )
        if state.current_action.output_contract == "Answer":
            state.answer = action_summary
        observation = ObservationRef(
            goal_id=state.current_action.goal_id,
            kind="action_result",
            provenance=observation_provenance("runtime", "executor", action_summary),
            trust="external",
            taint=frozenset({
                "external_content",
                "derived",
                *({"instruction"} if carries_instruction_taint else set()),
            }),
            summary=action_summary,
            payload={
                "action_id": state.current_action.action_id,
                "execution_intent": state.current_action.execution_intent,
                "step_ids": [step.step_id for step in state.invocation_batch.invocations],
            },
        )
        outcome = ActionOutcome(
            action_id=state.current_action.action_id,
            goal_id=state.current_action.goal_id,
            status="succeeded",
            output_contract=state.current_action.output_contract,
            artifact_ids=result_keys,
            observation=observation,
            provider_calls=state.provider_call_count,
        )
        _record_execution_outcomes(state, deps, outcome="succeeded")
        _append_execution_event(state, deps, "attempt_recorded", goal_id=state.current_action.goal_id, payload={
            "attempt": AttemptRef(
                action_id=state.current_action.action_id,
                execution_intent=state.current_action.execution_intent,
                status="succeeded",
                artifact_ids=result_keys,
            ).model_dump(mode="json"),
        })
        for additional in state.control.actions[1:]:
            additional_step = next(
                (step for step in state.invocation_batch.invocations if step.step_id == additional.action_id),
                None,
            )
            if additional_step is None or additional_step.status != "completed":
                continue
            _append_execution_event(state, deps, "attempt_recorded", goal_id=additional.goal_id, payload={
                "attempt": AttemptRef(
                    action_id=additional.action_id,
                    execution_intent=additional.execution_intent,
                    status="succeeded",
                    artifact_ids=(additional_step.output_artifact_id,) if additional_step.output_artifact_id else (),
                ).model_dump(mode="json"),
            })
            if _action_closes_goal(state, additional):
                _append_execution_event(state, deps, "goal_candidate_complete", goal_id=additional.goal_id)
        if _action_closes_goal(state, state.current_action):
            _append_execution_event(state, deps, "goal_candidate_complete", goal_id=state.current_action.goal_id)
        elif state.current_action.output_contract == "AgentArtifact":
            # Delegated artifacts require synthesis by the parent before completion.
            _append_execution_event(state, deps, "goal_activated", goal_id=state.current_action.goal_id)
        if isinstance(state.current_action.input, ProcedureActionInput):
            from personal_agent.runtime.contracts.task import ContextItem

            receipt_items = []
            for result in state.invocation_batch.results.values():
                if not isinstance(result, dict) or not result.get("note_id"):
                    continue
                note_id = str(result["note_id"])
                receipt_items.append(ContextItem(
                    item_id=note_id,
                    category="evidence",
                    kind="mutation_receipt",
                    provenance=state.current_action.input.procedure_id,
                    trust="evidence",
                    summary=str(result.get("summary") or result.get("title") or "")[:1000],
                    payload={
                        "note_id": note_id,
                        "title": str(result.get("title") or ""),
                        "summary": str(result.get("summary") or ""),
                    },
                    admission="admitted",
                ))
            if receipt_items and state.context_inventory is not None:
                existing_refs = set(state.context_inventory.items)
                unique_receipts = {
                    item.item_id: item for item in receipt_items
                    if item.item_id not in existing_refs
                }
                receipt_items = list(unique_receipts.values())
                state.context_inventory = state.context_inventory.with_items(*receipt_items)
                state.add_event("context_admitted", {
                    "trust_tier": "evidence",
                    "count": len(receipt_items),
                    "source": "mutation_receipt",
                    "admitted_as_instruction": False,
                })
            state.add_event("procedure_completed", {
                "procedure_id": state.current_action.input.procedure_id,
                "procedure_run_id": state.current_action.input.procedure_run_id,
                "goal_id": state.current_action.goal_id,
            })
    state.control.action_outcome = outcome
    if outcome.observation is not None and outcome.observation not in state.control.observations:
        state.control.observations.append(outcome.observation)
    if outcome.status == "succeeded" and outcome.observation is not None:
        goal = next((item for item in state.goals if item.goal_id == outcome.goal_id), None)
        admission = deps.evidence_admission.admit(
            outcome.observation,
            purpose="semantic_verification",
            criterion_scope=goal.success_criterion_ids if goal is not None else (),
        )
        state.evidence_admissions[admission.admission_id] = admission
        state.add_event("evidence_admission_decided", admission.model_dump(mode="json"))
    state.add_event("action_outcome", outcome.model_dump(mode="json"))
    if outcome.status == "succeeded":
        state.control.actions = []
    return {
        "control": state.control,
        "answer": state.answer,
        "task_runtime": state.task_runtime,
        "execution_events": state.execution_events,
        "context_inventory": state.context_inventory,
        "active_procedure": state.active_procedure,
        "evidence_admissions": state.evidence_admissions,
        "capability_execution_outcomes": state.capability_execution_outcomes,
        "errors": state.errors,
        "events": state.events,
    }


def _node_verify_goal_progress(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    if state.task_contract is None or state.task_runtime is None:
        return {}
    candidates = [item for item in state.goals if item.status == "candidate_complete"]
    for goal in candidates:
        verification_results = _goal_scoped_verification_results(state, goal.goal_id)
        execution_fact = None
        receipt_required = any(
            criterion.criterion_id in goal.success_criterion_ids
            and criterion.acceptance_contract == "MutationReceipt"
            for criterion in state.task_contract.success_criteria
        )
        resource_execution_required = any(
            resource.required_operations
            for resource in state.task_contract.resources_for_goal(goal.goal_id)
        )
        if (
            (receipt_required or resource_execution_required)
            and state.control.resolved_command is not None
            and state.control.resolved_command.route != "internal_reasoning"
        ):
            # Decision ownership: the immutable criterion/resource contract
            # uniquely determines whether a provider execution fact is needed.
            # Verification only checks the current immutable Command lineage;
            # it never treats the fact as semantic Goal success.
            execution_fact = deps.execution_fact_verifier.verify(
                state.control.resolved_command,
                tuple(verification_results),
            )
            state.execution_fact_reports[goal.goal_id] = execution_fact
            state.add_event("execution_fact_verified", execution_fact.model_dump(mode="json"))
        evidence = tuple(
            decision.evidence
            for decision in state.evidence_admissions.values()
            if decision.verdict == "accepted"
            and decision.evidence is not None
            and decision.evidence.admitted_purpose == "semantic_verification"
            and set(decision.evidence.criterion_scope).intersection(goal.success_criterion_ids)
        )
        evidence_refs = tuple(item.evidence_ref for item in evidence)
        accepted_observation_refs = {
            decision.observation_ref
            for decision in state.evidence_admissions.values()
            if decision.verdict == "accepted"
        }
        rejected_observation_refs = {
            decision.observation_ref
            for decision in state.evidence_admissions.values()
            if decision.verdict == "rejected"
        }
        rejected_step_ids = {
            str(step_id)
            for observation in state.control.observations
            if observation.observation_id in rejected_observation_refs
            for step_id in observation.payload.get("step_ids", ())
        }
        semantic_verification_results = [
            item for item in verification_results
            if str(item.get("_step_id") or "") not in rejected_step_ids
        ]
        action_observation = (
            state.control.action_outcome.observation
            if state.control.action_outcome is not None
            and state.control.action_outcome.goal_id == goal.goal_id
            else None
        )
        action_semantically_admitted = (
            action_observation is None
            or action_observation.observation_id in accepted_observation_refs
        )
        semantic_answer = state.answer if action_semantically_admitted else None
        verifier_profiles = _verifier_profiles(state, deps, goal)
        verification_items = _verification_context_items(
            state,
            goal,
            semantic_verification_results,
            evidence_refs,
            verifier_profiles,
            candidate_answer=semantic_answer,
        )
        projection = deps.context_manager.project_contract(
            verification_items,
            purpose="semantic_verification",
            budget=_context_budget(state),
            source_snapshot=_context_snapshot(state),
        )
        state.context_projections.append(projection)
        materialized = deps.context_gateway.open(
            projection, verification_items, purpose="semantic_verification",
        )
        semantic_context = None
        if (
            deps.goal_verifier.semantic_enabled
            and state.planning_usage.semantic_verifier_calls
            < state.planner_profile.limits.max_semantic_verifier_calls
        ):
            # Decision ownership: this is a transient projection of already
            # recorded execution facts for the model-owned semantic verifier.
            # It does not derive a Goal result or alter the Receipt report. In
            # particular, an external-state Goal has no user-facing answer by
            # design, so its semantics must be judged from its scoped outcome
            # and evidence rather than an empty answer slot.
            semantic_context = {
                **materialized.model_payload(),
                "goal_verification_input": {
                    "goal_id": goal.goal_id,
                    "result_contract": goal.result_contract,
                    "output_contract": goal.output_contract,
                    "candidate_answer": semantic_answer,
                    "action_outcome": (
                        state.control.action_outcome.model_dump(mode="json")
                        if state.control.action_outcome is not None
                        and state.control.action_outcome.goal_id == goal.goal_id
                        and action_semantically_admitted
                        else None
                    ),
                    "execution_fact_report": (
                        execution_fact.model_dump(mode="json")
                        if execution_fact is not None else None
                    ),
                },
            }
            state.planning_usage = state.planning_usage.model_copy(update={
                "semantic_verifier_calls": state.planning_usage.semantic_verifier_calls + 1,
            })
        report = deps.goal_verifier.verify(
            state.task_contract,
            goal,
            answer=semantic_answer,
            citation_count=len(state.citations) if len(state.goals) == 1 else 0,
            tool_results=tuple(semantic_verification_results),
            evidence=evidence,
            execution_fact_report=execution_fact,
            model_context=semantic_context,
        )
        state.verification_reports[goal.goal_id] = report
        _append_execution_event(state, deps, "verification_recorded", goal_id=goal.goal_id, payload={
            "verification": report.model_dump(mode="json"),
            "verification_ref": report.report_id,
        })
        if report.status == "passed":
            _append_execution_event(state, deps, "goal_verified", goal_id=goal.goal_id, payload={
                "verification": report.model_dump(mode="json"),
                "verification_ref": report.report_id,
                "evidence_gaps": (),
            })
        else:
            _append_execution_event(state, deps, "goal_activated", goal_id=goal.goal_id, payload={
                "verification": report.model_dump(mode="json"),
                "verification_ref": report.report_id,
                "evidence_gaps": report.unresolved_gaps,
            })
            from personal_agent.verification.contracts.reports import VerificationFeedback

            feedback = VerificationFeedback(
                verification_report_ref=report.report_id,
                unsatisfied_criterion_refs=tuple(
                    item.criterion_id for item in report.checked_criteria
                    if item.status != "passed"
                ),
                evidence_gaps=report.gaps,
                deterministic_fact_refs=(execution_fact.report_id,) if execution_fact else (),
                recovery_budget_remaining=max(
                    state.task_contract.constraints.revision_budget
                    - state.control.cross_stage_revision_cycles,
                    0,
                ),
            )
            state.verification_feedback[goal.goal_id] = feedback
            state.add_event("verification_feedback_created", feedback.model_dump(mode="json"))
        state.add_event("goal_verification", report.model_dump(mode="json"))
        for execution_outcome in state.capability_execution_outcomes:
            if execution_outcome.goal_id != goal.goal_id or execution_outcome.outcome != "succeeded":
                continue
            if any(
                item.execution_outcome_ref == execution_outcome.event_id
                for item in state.capability_effectiveness_outcomes
            ):
                continue
            effectiveness = CapabilityEffectivenessEvent(
                task_id=state.task_contract.task_id,
                goal_id=goal.goal_id,
                capability_ref=execution_outcome.capability_ref,
                execution_outcome_ref=execution_outcome.event_id,
                verification_ref=f"{goal.goal_id}:{state.task_runtime.revision}",
                verdict="effective" if report.status == "passed" else "inconclusive",
                criterion_ids=goal.success_criterion_ids,
            )
            state.capability_effectiveness_outcomes.append(effectiveness)
            deps.capability_ranker.store.append_effectiveness(effectiveness)
    if state.answer is not None and state.current_action is None:
        if state.goals and all(
            item.status == "verified" for item in state.goals
        ):
            finish_proposal = ControlProposal(
                base_task_revision=state.task_contract.revision,
                base_runtime_revision=state.task_runtime.revision,
                source="contract_derivation",
                decision=FinishDecision(
                    target_goal_id=state.goals[-1].goal_id,
                    basis=DecisionBasis(expected_state_change="task_completed"),
                    expected_progress="verified_direct_completion",
                    completion_claim=CompletionClaim(
                        goal_ids=tuple(item.goal_id for item in state.goals),
                        criterion_ids=tuple(
                            item.criterion_id for item in state.task_contract.success_criteria
                        ),
                    ),
                ),
            )
            state.control.proposal = finish_proposal
            state.decision_admission = deps.decision_admission.admit(
                state.task_contract, state.task_runtime, finish_proposal, state.control.state,
            )
            state.control.accepted_intent = deps.accepted_intent_compiler.compile(
                state.task_contract,
                state.task_runtime,
                finish_proposal,
                state.decision_admission,
            )
            state.control.resolved_command = deps.execution_command_resolver.resolve(
                state.task_contract,
                state.control.accepted_intent,
            )
            state.control_commits.append(deps.control_committer.commit(
                state.control,
                state.task_runtime,
                admission_ref=state.decision_admission.admission_id,
                admission_verdict=state.decision_admission.verdict,
                admission_proposal_ref=state.decision_admission.proposal_ref,
                expected_task_revision=state.task_contract.revision,
                expected_event_cursor=state.task_runtime.last_event_sequence,
            ))
            state.control.advance_phase("accepting_result")
            state.control.disposition = "propose_completion"
        else:
            state.control.advance_phase("accepting_result")
            state.control.disposition = "continue_control"
    return {
        "task_runtime": state.task_runtime,
        "execution_events": state.execution_events,
        "events": state.events,
        "control": state.control,
        "planning_usage": state.planning_usage,
        "context_projections": state.context_projections,
        "capability_effectiveness_outcomes": state.capability_effectiveness_outcomes,
        "execution_fact_reports": state.execution_fact_reports,
        "verification_reports": state.verification_reports,
        "verification_feedback": state.verification_feedback,
        "decision_admission": state.decision_admission,
        "control_commits": state.control_commits,
    }


def _record_execution_outcomes(
    state: RunCheckpoint,
    deps: ExecutiveContext,
    *,
    outcome: str,
) -> None:
    if state.task_contract is None or state.current_action is None:
        return
    for spec in state.control.resolved_actions:
        if spec.goal_id != state.current_action.goal_id or not spec.execution_grant_ref:
            continue
        grant = state.execution_grants.get(spec.execution_grant_ref)
        if grant is None:
            continue
        capability_ref = next(
            (
                item.capability_ref
                for item in grant.dependency_set.availability_dependencies
                if item.capability_ref
            ),
            "",
        )
        if not capability_ref:
            capability_ref = str(getattr(grant, "capability_ref", ""))
        if not capability_ref:
            continue
        invocation_ref = next(
            (
                item.step_id for item in state.invocation_batch.invocations
                if item.execution_grant_ref == spec.execution_grant_ref
            ),
            spec.action_id,
        )
        if any(
            item.invocation_ref == invocation_ref and item.outcome == outcome
            for item in state.capability_execution_outcomes
        ):
            continue
        event = CapabilityExecutionOutcomeEvent(
            task_id=state.task_contract.task_id,
            goal_id=spec.goal_id,
            action_ref=spec.action_id,
            invocation_ref=invocation_ref,
            grant_ref=spec.execution_grant_ref,
            capability_ref=capability_ref,
            outcome=outcome,
        )
        state.capability_execution_outcomes.append(event)
        deps.capability_ranker.store.append_execution(event)


def _goal_scoped_verification_results(
    state: RunCheckpoint,
    goal_id: str,
) -> list[dict]:
    goal_step_ids = {
        item.step_id for item in state.invocation_batch.invocations if item.goal_id == goal_id
    }
    results = [
        item for item in state.tool_results
        if isinstance(item, dict)
        and (item.get("_goal_id") == goal_id or item.get("_step_id") in goal_step_ids)
    ]
    tool_step_ids = {
        str(item.get("_step_id")) for item in results if item.get("_step_id")
    }
    results.extend(
        item for step_id, item in state.invocation_batch.results.items()
        if step_id in goal_step_ids
        and step_id not in tool_step_ids
        and isinstance(item, dict)
    )
    return results


def _node_verify_completion(state: RunCheckpoint, *, deps: ExecutiveContext) -> dict:
    if state.task_contract is None or state.task_runtime is None:
        raise RuntimeError("completion verification requires task and ledger")
    decision = (
        state.control.accepted_intent.decision
        if state.control.accepted_intent is not None else None
    )
    claim = decision.completion_claim if isinstance(decision, FinishDecision) else None
    report = deps.completion_verifier.verify(
        state.task_contract,
        state.task_runtime,
        claim,
        verification_reports=state.verification_reports,
        pending_confirmation=state.control.pending_interaction is not None,
    )
    state.completion_report = report
    state.add_event("completion_checked", report.model_dump(mode="json"))
    if report.status == "complete":
        state.control.advance_phase("closed")
        _append_execution_event(state, deps, "task_completed", payload={
            "verified_goal_ids": report.verified_goal_ids,
        })
    else:
        state.control.advance_phase("preparing_model_call")
        state.control.disposition = "continue_control"
        observation = ObservationRef(
            kind="completion_gap",
            provenance=observation_provenance(
                "runtime",
                "completion_verifier",
                ", ".join(report.reason_codes) or "completion rejected",
            ),
            trust="trusted",
            taint=frozenset({"derived"}),
            summary=", ".join(report.reason_codes) or "completion rejected",
            payload=report.model_dump(mode="json"),
        )
        state.control.observations.append(observation)
        _append_execution_event(state, deps, "completion_rejected", payload=report.model_dump(mode="json"))
        state.add_event("completion_rejected", report.model_dump(mode="json"))
    return {
        "task_contract": state.task_contract,
        "active_procedure": state.active_procedure,
        "control": state.control,
        "completion_report": state.completion_report,
        "task_runtime": state.task_runtime,
        "execution_events": state.execution_events,
        "events": state.events,
        "capability_effectiveness_outcomes": state.capability_effectiveness_outcomes,
    }


def _verifier_profiles(
    state: RunCheckpoint,
    deps: ExecutiveContext,
    goal,
) -> tuple[str, ...]:
    profiles = []
    if state.task_runtime is None or state.task_contract is None:
        return ()
    domains = {
        item.semantic_domain
        for item in state.task_contract.resources_for_goal(goal.goal_id)
    }
    for skill_id in state.task_runtime.active_skill_ids:
        try:
            skill = deps.controller.skills.get(deps.controller.tenant_id, skill_id)
        except (KeyError, PermissionError):
            continue
        if (
            domains.intersection(skill.manifest.applicability.semantic_domains)
            or state.task_contract.result_contract in skill.manifest.applicability.result_contracts
        ):
            profiles.append(skill.manifest.verifier_profile)
    return tuple(dict.fromkeys(item for item in profiles if item))


def _after_apply_decision(state: RunCheckpoint) -> str:
    decision = (
        state.control.accepted_intent.decision
        if state.control.accepted_intent is not None else None
    )
    if isinstance(decision, (ExecuteBoundedActionDecision, DelegateDecision, InvokeProcedureDecision)):
        return "action"
    if isinstance(decision, FinishDecision):
        return "completion"
    if isinstance(decision, TerminateDecision):
        return "stop"
    if isinstance(decision, RequestCapabilityAcquisitionDecision):
        return "interrupt_capability_acquisition"
    if isinstance(decision, RequestConfirmationDecision):
        return "interrupt_confirmation"
    return "loop"


def _node_interrupt_confirmation(state: RunCheckpoint) -> dict:
    """Resume a persisted confirmation and append only the user decision fact.

    Decision ownership: this node cannot select a route or an intent.  The
    next turn remains a model Proposal subject to ordinary admission.
    """
    pending = state.control.pending_interaction
    intent = state.control.accepted_intent
    if pending is None or intent is None:
        raise RuntimeError("confirmation interrupt requires a persisted interaction and intent")
    if not isinstance(intent.decision, RequestConfirmationDecision):
        raise RuntimeError("confirmation interrupt requires a confirmation intent")

    resume_value = interrupt(pending.model_dump(mode="json"))
    requested = (
        str(resume_value.get("decision", "reject")).lower()
        if isinstance(resume_value, dict) else "reject"
    )
    decision = "confirmed" if requested in {"confirm", "confirmed", "approve", "approved"} else "rejected"
    state.control.pending_interaction = None
    state.control.interaction_decision = decision
    state.control.observations.append(ObservationRef(
        goal_id=intent.goal_id,
        kind="user_confirmation",
        provenance=observation_provenance("user", "user", str(resume_value)),
        trust="scoped",
        summary=decision,
        payload={
            "decision": decision,
            "authorization_digest": pending.authorization_digest,
        },
    ))
    state.control.advance_phase("preparing_model_call")
    state.control.disposition = "continue_control"
    state.add_event("confirmation_resumed", {
        "step_id": pending.step_id,
        "decision": decision,
        "authorization_digest": pending.authorization_digest,
    })
    return {"control": state.control, "events": state.events}


def _node_interrupt_capability_acquisition(
    state: RunCheckpoint,
    *,
    deps: ExecutiveContext,
) -> dict:
    """Resume one persisted acquisition request without claiming capability."""
    pending = state.control.pending_interaction
    intent = state.control.accepted_intent
    if pending is None or intent is None:
        raise RuntimeError("capability acquisition interrupt requires persisted state")
    if not isinstance(intent.decision, RequestCapabilityAcquisitionDecision):
        raise RuntimeError("capability acquisition interrupt requires acquisition intent")
    request_id = pending.step_id
    if request_id not in state.capability_acquisition.requests:
        raise RuntimeError("capability acquisition request is not checkpointed")

    response = interrupt(pending.model_dump(mode="json"))
    requested = (
        str(response.get("decision", "reject")).lower()
        if isinstance(response, dict) else "reject"
    )
    approved = requested in {"confirm", "confirmed", "approve", "approved"}
    state.capability_acquisition = deps.capability_acquisition_manager.decide(
        state.capability_acquisition,
        request_id,
        approved=approved,
    )
    state.control.pending_interaction = None
    state.control.interaction_decision = "confirmed" if approved else "rejected"
    state.answer = (
        "能力获取请求已批准；任务已暂停，待环境能力更新后可重新执行。"
        if approved else "能力获取请求已取消。"
    )
    state.control.advance_phase("closed")
    state.control.disposition = "pause" if approved else "terminate"
    if approved:
        _append_execution_event(state, deps, "task_paused", payload={
            "reason": "capability_acquisition_pending",
        })
    else:
        _append_execution_event(state, deps, "task_terminated", payload={
            "reason": "user_cancelled",
            "reason_code": "capability_acquisition_denied",
        })
    state.add_event("capability_acquisition_decided", {
        "request_id": request_id,
        "approved": approved,
        "goal_progress": False,
    })
    return {
        "capability_acquisition": state.capability_acquisition,
        "control": state.control,
        "task_runtime": state.task_runtime,
        "execution_events": state.execution_events,
        "answer": state.answer,
        "events": state.events,
    }


def _after_completion(state: RunCheckpoint) -> str:
    if state.completion_report and state.completion_report.status == "complete":
        return "complete"
    return "loop"


def _route_update(
    state: RunCheckpoint,
    route: str,
) -> dict:
    phase, disposition = {
        "loop": ("preparing_model_call", "continue_control"),
        "action": ("routing", "continue_control"),
        "completion": ("accepting_result", "propose_completion"),
        "stop": ("closed", "terminate"),
    }[route]
    state.control.advance_phase(phase)
    state.control.disposition = disposition
    return {
        "control": state.control,
        "invocation_batch": state.invocation_batch,
        "task_runtime": state.task_runtime,
        "execution_events": state.execution_events,
        "context_inventory": state.context_inventory,
        "task_contract": state.task_contract,
        "active_procedure": state.active_procedure,
        "execution_grants": state.execution_grants,
        "answer": state.answer,
        "events": state.events,
    }


def _step_for_action(state: RunCheckpoint, action: BoundedAction) -> ExecutableInvocation:
    domains = set(action.requirement.semantic_domains) if action.requirement else set()
    external_acquire = bool(domains - {"knowledge", "conversation"})
    action_type = {
        "acquire": "tool_call" if external_acquire else "retrieve",
        "explore": "tool_call",
        "reason": "compose",
        "transform": "compose",
        "verify": "verify",
        "delegate": "agent_call",
        "commit": "commit",
    }.get(action.execution_intent, "compose")
    use_agentic_synthesis = (
        action.input.agentic_synthesis
        if isinstance(action.input, CapabilityActionInput) else False
    )
    execution_mode = "react" if (
        action.execution_intent == "explore"
        or (action.execution_intent == "acquire" and external_acquire)
        or (
            action.execution_intent in {"reason", "transform"}
            and use_agentic_synthesis
        )
    ) else "deterministic"
    requirements = []
    if action.requirement is not None:
        requirements = [action.requirement]
    return ExecutableInvocation(
        step_id=action.action_id,
        action_type=action_type,
        description=action.description,
        expected_output=action.output_contract,
        success_criteria="produce the declared output contract",
        risk_level="medium" if action.execution_intent == "commit" else "low",
        requires_confirmation=action.execution_intent == "commit",
        on_failure="retry",
        execution_mode=execution_mode,
        max_iterations=action.max_iterations,
        projection_kind="bounded_action",
        goal_id=action.goal_id,
        task_input=(action.input.task_text if hasattr(action.input, "task_text") else action.description),
        execution_intent=action.execution_intent,
        output_contract=action.output_contract,
        capability_requirements=requirements,
        skill_ids=list(state.task_runtime.active_skill_ids) if state.task_runtime else [],
        execution_guidance=list(
            action.input.execution_guidance
            if isinstance(action.input, CapabilityActionInput) else ()
        ),
    )


def _steps_for_action(
    state: RunCheckpoint,
    action: BoundedAction,
) -> tuple[ExecutableInvocation, ...]:
    commit = _step_for_action(state, action)
    if action.execution_intent != "commit":
        return (commit,)
    proposal = ExecutableInvocation(
        step_id=f"{action.action_id}:proposal",
        action_type="resolve",
        description=f"Propose a scoped mutation for: {action.description}",
        expected_output="ProposedCommit",
        success_criteria="return a supported proposed_commit or explicitly decline",
        execution_mode="react",
        max_iterations=action.max_iterations,
        projection_kind="bounded_action",
        goal_id=action.goal_id,
        task_input=(action.input.task_text if hasattr(action.input, "task_text") else action.description),
        execution_intent="explore",
        output_contract="ProposedCommit",
        skill_ids=list(state.task_runtime.active_skill_ids) if state.task_runtime else [],
        execution_guidance=list(
            action.input.execution_guidance
            if isinstance(action.input, CapabilityActionInput) else ()
        ),
    )
    commit.depends_on = [proposal.step_id]
    commit.execution_mode = "deterministic"
    return proposal, commit


def _materialize_delegate(
    state: RunCheckpoint,
    deps: ExecutiveContext,
    decision: DelegateDecision,
) -> tuple[BoundedAction, ExecutableInvocation, CapabilityGapObservation | None]:
    requirement = decision.subtask.required_capability
    registry = build_capability_portfolio(agents=deps.agent_gateway.profiles())
    resolution = CapabilityResolver(
        registry,
        policy_engine=deps.policy_engine,
        ranker=deps.capability_ranker,
    ).resolve(
        ExecutionCapabilityRequest(
            task_id=state.task_contract.task_id if state.task_contract else "",
            goal_id=decision.target_goal_id,
            action_id=decision.subtask.subtask_id,
            execution_intent="delegate",
            allowed_kinds=("agent",),
            allowed_operations=("delegate",),
            requirements=(requirement,),
            policy=CapabilitySelectionPolicy(read_only=True),
            runtime_context=CapabilityRuntimeContext(
                equivalence_class=CapabilityEquivalenceClass(
                    required_output_contract=decision.subtask.expected_artifact_contract,
                    allowed_side_effect_class="none",
                    authority_scope=canonical_digest({
                        "selector": requirement.selector,
                        "operations": requirement.operations,
                    }),
                    trust_floor=requirement.minimum_trust_level,
                    freshness_contract="fresh" if requirement.freshness_required else "current",
                    evidence_contract=decision.subtask.expected_artifact_contract,
                    data_egress_class="content",
                    failure_semantics="return_typed_failure",
                ),
            ),
        )
    )
    selected = resolution.selected_definition
    if selected is None or selected.kind != "agent" or any(
        item.status != "satisfied" for item in resolution.coverage
    ):
        coverage = resolution.coverage[0] if resolution.coverage else None
        gap = CapabilityGapObservation(
            goal_id=decision.target_goal_id,
            provenance=observation_provenance(
                "runtime",
                "capability_resolver",
                coverage.rationale if coverage else "no agent capability available",
            ),
            trust="trusted",
            taint=frozenset({"derived"}),
            summary=coverage.rationale if coverage else "no agent capability available",
            requirement_id=requirement.requirement_id,
            status=coverage.status if coverage and coverage.status != "satisfied" else "unavailable",
            missing_operations=tuple(coverage.missing_operations) if coverage else tuple(requirement.operations),
            attempted_capability_classes=("agent",),
            suggested_capability_classes=("local_tool", "mcp_tool"),
        )
        empty_action = BoundedAction(
            goal_id=decision.target_goal_id,
            execution_intent="delegate",
            description=decision.subtask.goal,
            output_contract=decision.subtask.expected_artifact_contract,
            requirement=requirement,
            input=CapabilityActionInput(task_text=decision.subtask.goal),
        )
        return empty_action, ExecutableInvocation(
            action_type="agent_call",
            description=decision.subtask.goal,
        ), gap
    agent_id = str(selected.local_name or selected.capability_id)
    profile = deps.agent_gateway.profile(agent_id)
    if profile is None:
        raise RuntimeError("resolved subagent profile disappeared")
    selected_ids = (selected.capability_id,)
    effective_scope = deps.subagent_runtime.effective_scope(
        profile=profile,
        parent_capability_ids=selected_ids,
        parent_operations=requirement.operations,
        policy_capability_ids=selected_ids,
        policy_operations=requirement.operations,
        subtask=decision.subtask,
    )
    if "delegate" not in effective_scope.operations:
        raise PermissionError("subagent effective scope does not allow delegation")
    reservation = deps.subagent_runtime.reserve(
        parent_run_id=state.run_id,
        child_run_id=decision.subtask.subtask_id,
        subtask=decision.subtask,
        parent_token_remaining=(
            state.task_contract.constraints.token_budget
            if state.task_contract and state.task_contract.constraints.token_budget
            else decision.subtask.token_budget
        ),
        parent_cost_remaining=decision.subtask.cost_budget,
        parent_time_remaining=decision.subtask.time_budget_seconds,
    )
    action = BoundedAction(
        action_id=decision.subtask.subtask_id,
        goal_id=decision.target_goal_id,
        execution_intent="delegate",
        description=decision.subtask.goal,
        output_contract="AgentArtifact",
        requirement=requirement,
        max_tool_calls=decision.subtask.max_provider_calls,
        max_model_calls=0,
        input=DelegateActionInput(
            task_text=decision.subtask.goal,
            agent_id=agent_id,
            capability_ids=effective_scope.capability_ids,
            operations=effective_scope.operations,
            token_budget=reservation.token_budget,
            cost_budget=reservation.cost_budget,
            time_budget_seconds=reservation.time_budget_seconds,
        ),
    )
    step = _step_for_action(state, action)
    step.agent_id = agent_id
    step.subtask = DelegatedSubtaskInvocation(
        goal=decision.subtask.goal,
        parent_goal_id=decision.subtask.parent_goal_id,
        context_projection_ids=decision.subtask.context_projection_ids,
        required_capability=requirement,
        expected_artifact_contract=decision.subtask.expected_artifact_contract,
        verification_policy=decision.subtask.verification_policy,
        max_provider_calls=decision.subtask.max_provider_calls,
        requested_operations=decision.subtask.requested_operations,
    )
    step.capability_requirements = [requirement]
    return action, step, None


def _action_summary(state: RunCheckpoint) -> str:
    results = [
        value for value in state.invocation_batch.results.values()
        if value is not None
    ]
    for result in reversed(results):
        if isinstance(result, dict) and result.get("answer"):
            return str(result["answer"])[:1500]
    if state.answer:
        return state.answer[:1500]
    return str(results[-1])[:1500] if results else "action completed"


def _action_closes_goal(state: RunCheckpoint, action: BoundedAction) -> bool:
    if isinstance(action.input, ProcedureActionInput):
        return True
    if state.task_runtime is None:
        return False
    goal = next(
        (item for item in state.goals if item.goal_id == action.goal_id),
        None,
    )
    if goal is None:
        return False
    return action.output_contract == goal.output_contract


def _context_items(state: RunCheckpoint):
    return tuple(state.context_inventory.items.values())


def _planning_context_items(state: RunCheckpoint, procedures) -> tuple[ContextItem, ...]:
    if state.task_contract is None or state.task_runtime is None:
        return _context_items(state)
    runtime = ContextItem(
        item_id=(
            f"planning:{state.task_contract.task_id}:{state.task_contract.revision}:"
            f"{state.task_runtime.goal_graph_revision}"
        ),
        category="run",
        kind="planning_state",
        provenance="runtime",
        trust="runtime",
        summary=state.task_contract.user_goal,
        payload={
            "task": state.task_contract.model_dump(mode="json"),
            "goal_graph": [item.model_dump(mode="json") for item in state.goals],
            "procedures": [
                item.model_dump(mode="json") for item in procedures
                if item.status in {"eligible", "mandatory"}
            ],
            "budget": state.planning_usage.model_dump(mode="json"),
            "active_plan": (
                state.plan_definition.model_dump(mode="json")
                if state.plan_definition is not None else None
            ),
            "decision_feedback": [
                item.model_dump(mode="json")
                for item in state.decision_feedback[-4:]
                if item.stage == "planning"
            ],
            "plan_step_statuses": state.plan_runtime.step_statuses,
            "replan_request": (
                state.replan_request.model_dump(mode="json")
                if state.replan_request is not None else None
            ),
        },
        admission="admitted",
    )
    observations = tuple(ContextItem(
        item_id=f"observation:{item.observation_id}",
        category="observation",
        kind="observation",
        provenance=item.provenance.source_ref,
        trust="untrusted",
        summary=item.summary,
        payload=item.model_dump(mode="json"),
        admission="candidate",
    ) for item in state.control.observations[-8:])
    return (*_context_items(state), runtime, *observations)


def _monitor_context_items(state: RunCheckpoint) -> tuple[ContextItem, ...]:
    if state.task_contract is None or state.task_runtime is None:
        return _context_items(state)
    runtime = ContextItem(
        item_id=f"monitor:{state.task_contract.task_id}:{state.plan_runtime.last_event_sequence}",
        category="run",
        kind="plan_monitor_state",
        provenance="runtime",
        trust="runtime",
        summary=state.task_contract.user_goal,
        payload={
            "task_revision": state.task_contract.revision,
            "goal_graph_revision": state.task_runtime.goal_graph_revision,
            "active_plan": (
                state.plan_definition.model_dump(mode="json")
                if state.plan_definition is not None else None
            ),
            "step_statuses": state.plan_runtime.step_statuses,
            "selected_step_ids": tuple(state.selected_plan_step_ids),
            "authority_tier": "system_policy",
        },
        admission="admitted",
    )
    observations = tuple(ContextItem(
        item_id=f"monitor-observation:{item.observation_id}",
        category="observation",
        kind="observation",
        provenance=item.provenance.source_ref,
        trust="untrusted",
        summary=item.summary,
        payload=item.model_dump(mode="json"),
        admission="candidate",
    ) for item in state.control.observations[-6:])
    verification_feedback = tuple(ContextItem(
        item_id=f"verification-feedback:{goal_id}:{item.feedback_id}",
        category="observation",
        kind="verification_feedback",
        provenance="goal_verifier",
        trust="runtime",
        summary="; ".join(item.unsatisfied_criterion_refs),
        payload=item.model_dump(mode="json"),
        admission="admitted",
    ) for goal_id, item in state.verification_feedback.items())
    return (*_context_items(state), runtime, *observations, *verification_feedback)


def _verification_context_items(
    state: RunCheckpoint,
    goal,
    tool_results: list[dict],
    evidence_refs: tuple[str, ...],
    verifier_profiles: tuple[str, ...],
    *,
    candidate_answer: str | None,
) -> tuple[ContextItem, ...]:
    assert state.task_contract is not None
    criteria = tuple(
        item.model_dump(mode="json")
        for item in state.task_contract.success_criteria
        if item.criterion_id in goal.success_criterion_ids
    )
    runtime = ContextItem(
        item_id=f"verification:{state.task_contract.task_id}:{goal.goal_id}",
        category="run",
        kind="verification_contract",
        provenance="runtime",
        trust="runtime",
        summary=goal.description,
        payload={
            "goal": goal.description,
            "criteria": criteria,
            "constraints": [
                item.model_dump(mode="json")
                for item in goal.constraints
            ],
            "evidence_refs": evidence_refs,
            "verifier_profiles": verifier_profiles,
            "authority_tier": "system_policy",
        },
        admission="admitted",
    )
    answer = ContextItem(
        item_id=f"verification-answer:{goal.goal_id}",
        category="observation",
        kind="candidate_answer",
        provenance="agent_runtime",
        trust="untrusted",
        summary=(candidate_answer or "")[:2000],
        payload={"answer": (candidate_answer or "")[:12000]},
        admission="candidate",
    )
    evidence = tuple(ContextItem(
        item_id=f"verification-evidence:{goal.goal_id}:{index}",
        category="evidence",
        kind="goal_evidence",
        provenance="action_execution",
        trust="untrusted",
        summary=_safe_context_summary(item),
        payload={"evidence": item},
        admission="candidate",
    ) for index, item in enumerate(tool_results[:8]))
    return (runtime, answer, *evidence)


def _safe_context_summary(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:2000]


def _control_context_items(state: RunCheckpoint) -> tuple[ContextItem, ...]:
    if state.task_contract is None or state.task_runtime is None or state.control.state is None:
        return _context_items(state)
    runtime = ContextItem(
        item_id=(
            f"control:{state.task_contract.task_id}:{state.task_contract.revision}:"
            f"{state.task_runtime.revision}"
        ),
        category="run",
        kind="control_state",
        provenance="runtime",
        trust="runtime",
        summary=state.task_contract.user_goal,
        payload={
            "task": state.task_contract.model_dump(mode="json"),
            "goal_graph": [item.model_dump(mode="json") for item in state.goals],
            "control": state.control.state.model_dump(mode="json"),
            "active_plan": (
                state.plan_definition.model_dump(mode="json")
                if state.plan_definition is not None else None
            ),
            "ready_frontier": (
                state.frontier_decision.model_dump(mode="json")
                if state.frontier_decision is not None else None
            ),
            "decision_feedback": (
                state.decision_admission.feedback.model_dump(mode="json")
                if state.decision_admission is not None
                and state.decision_admission.feedback is not None else None
            ),
            "verification_feedback": {
                goal_id: feedback.model_dump(mode="json")
                for goal_id, feedback in state.verification_feedback.items()
            },
        },
        admission="admitted",
    )
    return (*_context_items(state), runtime)


def _context_budget(state: RunCheckpoint) -> ContextBudget:
    model_profile = "runtime-default"
    return ContextBudget(
        model_profile=model_profile,
        tokenizer_profile=model_profile,
        max_context_tokens=16_384,
        safety_margin=512,
        reserved_output_tokens=2_048,
    )


def _decision_semantic_hash(decision) -> str:
    payload = {
        "action": decision.action,
        "target_goal_id": decision.target_goal_id,
        "expected_progress": decision.expected_progress,
    }
    if isinstance(decision, ExecuteBoundedActionDecision):
        payload["execution_intent"] = decision.bounded_action.execution_intent
        payload["requirement"] = (
            decision.bounded_action.requirement.purpose
            if decision.bounded_action.requirement else ""
        )
    elif isinstance(decision, InvokeProcedureDecision):
        payload["procedure_id"] = decision.procedure_invocation.procedure.procedure_id
    elif isinstance(decision, DelegateDecision):
        payload["subtask_goal"] = decision.subtask.goal
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:16]


def _render_control_status(status: str, reason_codes: tuple[str, ...]) -> str:
    """Render canonical governance state without inventing a business answer."""
    reason = reason_codes[0] if reason_codes else "unspecified"
    messages = {
        "terminal": f"请求未通过治理管控，运行已停止（{reason}）。",
        "await_environment_change": f"当前环境暂不满足执行条件，运行已暂停（{reason}）。",
        "request_capability_acquisition": f"需要先补齐执行能力（{reason}）。",
    }
    return messages.get(status, f"运行状态已更新（{reason}）。")


__all__ = [
    "_after_action_resolution",
    "_after_decision_admission",
    "_after_decision_feedback",
    "_after_apply_decision",
    "_after_completion",
    "_node_apply_decision",
    "_node_admit_execution_route",
    "_node_admit_decision",
    "_node_decide",
    "_node_compile_goal_graph",
    "_node_observe_action",
    "_node_project_control_state",
    "_node_resolve_action",
    "_node_handle_decision_denial",
    "_node_interrupt_capability_acquisition",
    "_node_interrupt_confirmation",
    "_node_verify_completion",
    "_node_verify_goal_progress",
]
