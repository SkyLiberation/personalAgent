"""Nodes for the task-level executive control loop."""

from __future__ import annotations

from hashlib import sha256
import json
import logging

from langgraph.types import interrupt

from personal_agent.kernel.contracts.agentic import (
    AttemptRef,
    ContextBudget,
    ContextItem,
    ExecutionLedger,
)
from personal_agent.kernel.contracts.capability import (
    CapabilityResolutionRequest,
    CapabilitySelectionPolicy,
)
from personal_agent.kernel.contracts.execution import ExecutionStep
from personal_agent.kernel.contracts.executive import (
    ActionOutcome,
    ActivateSkillDecision,
    BoundedAction,
    CapabilityClassSummary,
    CapabilityGapObservation,
    ClarifyDecision,
    CompletionClaim,
    DecisionBasis,
    DelegateDecision,
    ExecuteMetaCapabilityDecision,
    FinishDecision,
    InvokeProcedureDecision,
    ObservationRef,
    ProposedResourceAccessPlan,
    RequestConfirmationDecision,
    StopDecision,
)
from personal_agent.orchestration.orchestration_contexts import ExecutiveContext
from personal_agent.orchestration.orchestration_models import AgentGraphState, StepExecutionState, StepRunState
from personal_agent.planning.capability_resolver import CapabilityResolver
from personal_agent.planning.direct import DirectAdmission, DirectCandidate
from personal_agent.planning.ledger import next_execution_event
from personal_agent.planning.recovery import classify_failure
from personal_agent.tools.mcp_capability import build_capability_registry

logger = logging.getLogger(__name__)


def _append_execution_event(
    state: AgentGraphState,
    deps: ExecutiveContext,
    event_type: str,
    *,
    goal_id: str | None = None,
    payload: dict | None = None,
) -> None:
    if state.execution_ledger is None:
        raise RuntimeError("execution ledger is not initialized")
    event = next_execution_event(
        state.execution_ledger,
        event_type,
        goal_id=goal_id,
        payload=payload,
    )
    state.execution_ledger = deps.ledger_projector.project(state.execution_ledger, (event,))
    state.execution_events.append(event)
    state.add_event("plan_ledger_updated", {
        "execution_event": event.model_dump(mode="json"),
        "ledger_revision": state.execution_ledger.revision,
    })


def _node_compile_goal_graph(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.task_analysis is None:
        raise RuntimeError("goal graph compilation requires task analysis")
    compilation = deps.goal_graph_compiler.compile(state.task_analysis, state.entry_text)
    state.task_spec = compilation.task_spec
    state.context_envelope = compilation.context_envelope
    state.execution_ledger = ExecutionLedger(task_id=compilation.task_spec.task_id)
    _append_execution_event(state, deps, "task_created", payload={
        "task_spec": state.task_spec.model_dump(mode="json"),
    })
    for item in compilation.ledger.items:
        _append_execution_event(state, deps, "goal_added", goal_id=item.goal_id, payload={
            "goal": item.model_dump(mode="json"),
        })
    state.executive_turn = 0
    state.control_decision = None
    state.current_action = None
    state.current_actions = []
    state.current_action_outcome = None
    state.completion_report = None
    state.latest_observations = []
    state.planning_model_context = {}
    state.control_model_context = {}
    from personal_agent.kernel.contracts.planning import PlanLedger, PlanningBudget
    state.planning_facts = None
    state.planning_mode = None
    state.planner_profile = deps.planner_profile
    state.planning_budget = PlanningBudget.model_validate(
        deps.planner_profile.planning_budget.model_dump()
    )
    state.plan_ledger = PlanLedger()
    state.frontier_decision = None
    state.selected_plan_step_ids = []
    state.plan_monitor_decision = None
    state.replan_request = None
    state.dispatch_groups = []
    state.add_event("goal_graph_compiled", {
        "task_id": state.task_spec.task_id,
        "revision": state.task_spec.revision,
        "goal_ids": [item.goal_id for item in state.execution_ledger.items],
    })
    if (
        state.task_analysis.direct_answer
        and len(state.execution_ledger.items) == 1
        and state.execution_ledger.items[0].result_contract == "response"
    ):
        candidate = DirectCandidate(
            goal=state.execution_ledger.items[0].description,
            criteria=state.task_spec.success_criteria,
            answer=state.task_analysis.direct_answer,
        )
        if DirectAdmission().admit(candidate, required_criteria=state.task_spec.success_criteria):
            state.answer = candidate.answer
            _append_execution_event(
                state,
                deps,
                "goal_candidate_complete",
                goal_id=state.execution_ledger.items[0].goal_id,
            )
            state.control_route = "direct_candidate"
            state.add_event("direct_candidate_admitted", {
                "goal_id": state.execution_ledger.items[0].goal_id,
                "criterion_ids": [item.criterion_id for item in state.task_spec.success_criteria],
            })
    return {
        "task_spec": state.task_spec,
        "execution_ledger": state.execution_ledger,
        "context_envelope": state.context_envelope,
        "context_projections": state.context_projections,
        "planning_model_context": state.planning_model_context,
        "control_model_context": state.control_model_context,
        "resolved_action_spec": state.resolved_action_spec,
        "resolved_action_specs": state.resolved_action_specs,
        "retry_directive": state.retry_directive,
        "active_procedure": state.active_procedure,
        "planning_facts": state.planning_facts,
        "planning_mode": state.planning_mode,
        "planner_profile": state.planner_profile,
        "planning_budget": state.planning_budget,
        "plan_ledger": state.plan_ledger,
        "frontier_decision": state.frontier_decision,
        "selected_plan_step_ids": state.selected_plan_step_ids,
        "dispatch_groups": state.dispatch_groups,
        "execution_events": state.execution_events,
        "events": state.events,
        "executive_turn": state.executive_turn,
        "answer": state.answer,
        "control_route": state.control_route,
    }


def _node_project_planning_facts(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.task_spec is None or state.execution_ledger is None:
        raise RuntimeError("planning facts require task and goal graph")
    procedures = deps.procedure_applicability_resolver.resolve(
        state.task_spec,
        state.execution_ledger,
    )
    planning_items = _planning_context_items(state, procedures)
    projection = deps.context_manager.project(
        planning_items,
        purpose="planning",
        budget=_context_budget(state),
        ledger_revision=state.execution_ledger.revision,
        event_cursor=str(state.execution_ledger.last_event_sequence),
    )
    state.context_projections.append(projection)
    materialized = deps.context_gateway.open(
        projection, planning_items, purpose="planning",
    )
    state.planning_model_context = materialized.model_payload()
    state.add_event("context_projected", projection.model_dump(mode="json"))
    state.add_event("context_materialized", {
        "projection_id": projection.projection_id,
        "purpose": "planning",
        "materialized_refs": materialized.materialized_refs,
    })
    from personal_agent.planning.adaptive import profile_for_task

    state.planner_profile = profile_for_task(state.task_spec, procedures)
    state.planning_facts = deps.planning_fact_projector.project(
        state.task_spec,
        state.execution_ledger,
        procedures,
        state.planner_profile,
    )
    state.add_event("planning_facts_projected", state.planning_facts.model_dump(mode="json"))
    return {
        "planning_facts": state.planning_facts,
        "planner_profile": state.planner_profile,
        "planning_model_context": state.planning_model_context,
        "context_projections": state.context_projections,
        "events": state.events,
    }


def _node_assess_planning_mode(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.planning_facts is None or state.execution_ledger is None:
        raise RuntimeError("planning mode requires projected facts")
    target_goal_ids = tuple(
        item.goal_id for item in state.execution_ledger.items
        if item.status not in {"verified", "degraded", "abandoned"}
    )
    state.planning_mode, state.planning_budget = deps.planning_mode_policy.assess(
        state.planning_facts,
        target_goal_ids=target_goal_ids,
        budget=state.planning_budget,
    )
    state.add_event("planning_mode_assessed", {
        **state.planning_mode.model_dump(mode="json"),
        "profile_id": state.planner_profile.profile_id,
        "authority": state.planner_profile.authority,
    })
    return {
        "planning_mode": state.planning_mode,
        "planning_budget": state.planning_budget,
        "events": state.events,
    }


def _node_create_or_revise_plan(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if (
        state.task_spec is None
        or state.execution_ledger is None
        or state.planning_mode is None
    ):
        raise RuntimeError("adaptive planning requires task, goal graph, and mode")
    procedures = deps.procedure_applicability_resolver.resolve(
        state.task_spec,
        state.execution_ledger,
    )
    planning_items = _planning_context_items(state, procedures)
    projection = deps.context_manager.project(
        planning_items,
        purpose="planning",
        budget=_context_budget(state),
        ledger_revision=state.execution_ledger.revision,
        event_cursor=str(state.execution_ledger.last_event_sequence),
    )
    state.context_projections.append(projection)
    materialized = deps.context_gateway.open(
        projection, planning_items, purpose="planning",
    )
    state.planning_model_context = materialized.model_payload()
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
        and state.planning_budget.horizon_replacements
        >= state.planning_budget.max_horizon_replacements
    ):
        state.control_route = "planning_blocked"
        state.add_event("adaptive_plan_replacement_budget_exhausted", {
            "request": state.replan_request.model_dump(mode="json"),
            "budget": state.planning_budget.model_dump(mode="json"),
        })
        state.replan_request = None
        return {
            "planning_budget": state.planning_budget,
            "replan_request": None,
            "control_route": state.control_route,
            "events": state.events,
        }
    if (
        state.replan_request is not None
        and state.plan_ledger.plan is not None
        and state.replan_request.reason_code not in replacement_reasons
    ):
        patch, state.planning_budget = deps.adaptive_planner.create_patch(
            state.task_spec,
            state.plan_ledger,
            state.replan_request,
            state.planning_budget,
            model_context=state.planning_model_context,
        )
        if patch is None:
            state.control_route = "planning_blocked"
            state.add_event("adaptive_plan_patch_unavailable", {
                "request": state.replan_request.model_dump(mode="json"),
            })
        else:
            candidate_ledger = deps.plan_ledger_projector.apply_patch(
                state.plan_ledger,
                patch,
            )
            assert candidate_ledger.plan is not None
            deps.plan_validator.validate(
                candidate_ledger.plan,
                state.task_spec,
                state.execution_ledger,
                state.planner_profile,
            )
            state.plan_ledger = candidate_ledger
            state.planning_budget = state.planning_budget.model_copy(update={
                "applied_patches": state.planning_budget.applied_patches + 1,
            })
            state.control_route = "plan_ready"
            state.add_event("adaptive_plan_patched", patch.model_dump(mode="json"))
        state.replan_request = None
        return {
            "plan_ledger": state.plan_ledger,
            "planning_budget": state.planning_budget,
            "replan_request": state.replan_request,
            "control_route": state.control_route,
            "events": state.events,
            "context_projections": state.context_projections,
        }
    plan, state.planning_budget = deps.adaptive_planner.create_plan(
        state.task_spec,
        state.execution_ledger,
        state.planning_mode,
        procedures,
        state.planning_budget,
        model_context=state.planning_model_context,
        observation_ids=tuple(
            item.observation_id for item in state.latest_observations[-6:]
        ),
        gap_ids=tuple(
            gap for item in state.execution_ledger.items for gap in item.evidence_gaps
        ),
    )
    if plan is None:
        state.plan_ledger = state.plan_ledger.model_copy(update={"plan": None})
        state.control_route = "planning_blocked"
        state.add_event("adaptive_plan_unavailable", {
            "reason_code": "planner_could_not_produce_safe_plan",
            "budget": state.planning_budget.model_dump(mode="json"),
        })
    else:
        deps.plan_validator.validate(
            plan,
            state.task_spec,
            state.execution_ledger,
            state.planner_profile,
        )
        replacing = state.plan_ledger.plan is not None
        state.plan_ledger = (
            deps.plan_ledger_projector.replace(state.plan_ledger, plan)
            if replacing else deps.plan_ledger_projector.create(plan)
        )
        state.control_route = "plan_ready"
        if replacing:
            state.planning_budget = state.planning_budget.model_copy(update={
                "horizon_replacements": state.planning_budget.horizon_replacements + 1,
            })
        state.add_event("adaptive_plan_created", {
            "plan": plan.model_dump(mode="json"),
            "replacing": replacing,
        })
    state.replan_request = None
    return {
        "plan_ledger": state.plan_ledger,
        "planning_budget": state.planning_budget,
        "replan_request": state.replan_request,
        "control_route": state.control_route,
        "events": state.events,
        "context_projections": state.context_projections,
    }


def _node_monitor_plan(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.task_spec is None or state.execution_ledger is None:
        raise RuntimeError("plan monitoring requires task and goal graph")
    if state.plan_ledger.plan is not None:
        status_by_goal = {
            item.goal_id: item.status for item in state.execution_ledger.items
        }
        for step_id in tuple(state.selected_plan_step_ids):
            step = next(
                (item for item in state.plan_ledger.plan.steps if item.step_id == step_id),
                None,
            )
            if step is None:
                continue
            if status_by_goal.get(step.goal_id) in {"verified", "degraded"}:
                state.plan_ledger = deps.plan_ledger_projector.append(
                    state.plan_ledger,
                    "step_satisfied",
                    step_ids=(step_id,),
                )
            elif state.latest_observations:
                latest = state.latest_observations[-1]
                if not latest.goal_id or latest.goal_id == step.goal_id:
                    state.plan_ledger = deps.plan_ledger_projector.append(
                        state.plan_ledger,
                        "step_observed",
                        step_ids=(step_id,),
                        observation_ids=(latest.observation_id,),
                    )
    monitor_items = _monitor_context_items(state)
    projection = deps.context_manager.project(
        monitor_items,
        purpose="plan_monitoring",
        budget=_context_budget(state),
        ledger_revision=state.execution_ledger.revision,
        event_cursor=str(state.execution_ledger.last_event_sequence),
    )
    state.context_projections.append(projection)
    materialized = deps.context_gateway.open(
        projection, monitor_items, purpose="plan_monitoring",
    )
    state.plan_monitor_decision, state.plan_ledger = deps.plan_monitor.inspect(
        state.task_spec,
        state.execution_ledger,
        state.plan_ledger,
        tuple(state.latest_observations),
        state.planning_budget,
        model_context=materialized.model_payload(),
    )
    if state.plan_monitor_decision.decision_source == "semantic":
        state.planning_budget = state.planning_budget.model_copy(update={
            "semantic_monitor_calls": state.planning_budget.semantic_monitor_calls + 1,
        })
    state.replan_request = state.plan_monitor_decision.replan_request
    if (
        state.plan_monitor_decision.impact in {"step_invalidated", "branch_invalidated"}
        and state.plan_monitor_decision.affected_step_ids
    ):
        state.plan_ledger = deps.plan_ledger_projector.append(
            state.plan_ledger,
            "step_invalidated",
            step_ids=state.plan_monitor_decision.affected_step_ids,
        )
    state.control_route = (
        "replan" if state.plan_monitor_decision.action in {"patch", "replace"}
        else "planning_stop" if state.plan_monitor_decision.action in {"request_input", "stop"}
        else "control"
    )
    state.add_event("plan_monitored", state.plan_monitor_decision.model_dump(mode="json"))
    return {
        "plan_ledger": state.plan_ledger,
        "plan_monitor_decision": state.plan_monitor_decision,
        "replan_request": state.replan_request,
        "control_route": state.control_route,
        "planning_budget": state.planning_budget,
        "context_projections": state.context_projections,
        "events": state.events,
    }


def _node_project_control_state(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.task_spec is None or state.execution_ledger is None:
        raise RuntimeError("control state requires task and ledger")
    registry = build_capability_registry(
        tools=deps.tool_executor.list_tools(exposures={"public_agent", "scoped_agent", "admin"}),
        agents=deps.agent_gateway.profiles(),
    )
    grouped: dict[str, dict[str, set[str]]] = {}
    for capability in registry.list():
        bucket = grouped.setdefault(capability.kind, {
            "domains": set(), "operations": set(), "providers": set(),
        })
        bucket["domains"].update(capability.semantic_domains)
        bucket["operations"].update(capability.operations)
        bucket["providers"].add(capability.provider)
    summaries = tuple(CapabilityClassSummary(
        kind=kind,
        semantic_domains=tuple(sorted(values["domains"])),
        operations=tuple(sorted(values["operations"])),
        providers=tuple(sorted(values["providers"])),
    ) for kind, values in sorted(grouped.items()))
    from personal_agent.kernel.contracts.executive import ControlState

    state.control_state = ControlState(
        task_id=state.task_spec.task_id,
        task_revision=state.task_spec.revision,
        task_goal=state.task_spec.user_goal,
        ledger_revision=state.execution_ledger.revision,
        active_goal_ids=state.execution_ledger.active_goal_ids,
        active_skill_ids=state.execution_ledger.active_skill_ids,
        available_capability_classes=summaries,
        procedure_candidates=deps.procedure_applicability_resolver.resolve(
            state.task_spec,
            state.execution_ledger,
        ),
        outstanding_evidence_gaps=tuple(
            gap for item in state.execution_ledger.items for gap in item.evidence_gaps
        ),
        pending_approval_ids=(str(state.pending_confirmation.get("step_id")),)
        if state.pending_confirmation else (),
        latest_observations=tuple(state.latest_observations[-6:]),
        remaining_provider_calls=max(
            state.task_spec.constraints.max_provider_calls - state.provider_call_count, 0,
        ),
        remaining_executive_turns=max(
            state.task_spec.constraints.max_executive_turns - state.executive_turn, 0,
        ),
    )
    state.add_event("control_state_projected", {
        "task_id": state.control_state.task_id,
        "ledger_revision": state.control_state.ledger_revision,
        "remaining_executive_turns": state.control_state.remaining_executive_turns,
    })
    control_items = _control_context_items(state)
    projection = deps.context_manager.project(
        control_items,
        purpose="executive_decision",
        budget=_context_budget(state),
        ledger_revision=state.execution_ledger.revision,
        event_cursor=str(state.execution_ledger.last_event_sequence),
    )
    state.context_projections.append(projection)
    materialized = deps.context_gateway.open(
        projection, control_items, purpose="executive_decision",
    )
    state.control_model_context = materialized.model_payload()
    state.add_event("context_projected", projection.model_dump(mode="json"))
    return {
        "control_state": state.control_state,
        "context_projections": state.context_projections,
        "control_model_context": state.control_model_context,
        "events": state.events,
    }


def _node_decide(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.task_spec is None or state.execution_ledger is None or state.control_state is None:
        raise RuntimeError("executive decision requires projected control state")
    if state.control_state.remaining_executive_turns <= 0:
        goal_id = state.execution_ledger.active_goal_ids[0] if state.execution_ledger.active_goal_ids else "task"
        from personal_agent.kernel.contracts.executive import DecisionBasis

        decision = StopDecision(
            target_goal_id=goal_id,
            basis=DecisionBasis(expected_state_change="task_stopped"),
            expected_progress="budget_stop",
            reason_code="executive_turn_budget_exhausted",
            user_message="任务达到最大决策轮数，已停止并保留当前结果。",
        )
    else:
        open_goals = tuple(
            item for item in state.execution_ledger.items
            if item.status not in {"verified", "degraded", "abandoned"}
        )
        if not open_goals:
            # Completion preempts frontier selection. The controller only
            # proposes Finish; CompletionVerifier remains the sole authority.
            decision = deps.controller.decide(
                state.task_spec,
                state.execution_ledger,
                observations=tuple(state.latest_observations),
                capability_classes=state.control_state.available_capability_classes,
                control_state=state.control_state,
                model_context=state.control_model_context,
            )
        elif state.planning_mode is not None and state.planning_mode.mode == "deliberative":
            frontier = deps.plan_ledger_projector.frontier(state.plan_ledger)
            state.frontier_decision = deps.frontier_selector.select(
                frontier,
                state.planner_profile,
            )
            if state.frontier_decision is None:
                decision = StopDecision(
                    target_goal_id=(
                        state.execution_ledger.active_goal_ids[0]
                        if state.execution_ledger.active_goal_ids else "task"
                    ),
                    reason_code="plan_frontier_empty",
                    user_message="当前计划没有可安全执行的步骤，任务已停止。",
                )
            elif len(state.frontier_decision.selected_step_ids) != 1:
                decision = StopDecision(
                    target_goal_id=frontier[0].goal_id,
                    reason_code="parallel_profile_not_enabled",
                    user_message="当前执行 profile 尚未开放并行调度，任务已停止。",
                )
            else:
                selected_id = state.frontier_decision.selected_step_ids[0]
                step = next(item for item in frontier if item.step_id == selected_id)
                state.selected_plan_step_ids = [selected_id]
                state.plan_ledger = deps.plan_ledger_projector.append(
                    state.plan_ledger,
                    "frontier_selected",
                    step_ids=(selected_id,),
                    payload={
                        "decision": state.frontier_decision.model_dump(mode="json"),
                    },
                )
                decision = deps.controller.decide_plan_step(
                    state.task_spec,
                    state.execution_ledger,
                    step,
                    observations=tuple(state.latest_observations),
                    control_state=state.control_state,
                )
        else:
            state.frontier_decision = None
            state.selected_plan_step_ids = []
            decision = deps.controller.decide(
                state.task_spec,
                state.execution_ledger,
                observations=tuple(state.latest_observations),
                capability_classes=state.control_state.available_capability_classes,
                control_state=state.control_state,
                model_context=state.control_model_context,
            )
    state.executive_turn += 1
    semantic_hash = _decision_semantic_hash(decision)
    if semantic_hash == state.last_decision_hash:
        state.repeated_decision_count += 1
    else:
        state.repeated_decision_count = 0
    state.last_decision_hash = semantic_hash
    if state.repeated_decision_count >= 2:
        from personal_agent.kernel.contracts.executive import DecisionBasis

        decision = StopDecision(
            target_goal_id=decision.target_goal_id,
            basis=DecisionBasis(
                triggering_observation_ids=decision.basis.triggering_observation_ids,
                expected_state_change="task_stopped",
                rejected_action_codes=("repeated_decision",),
            ),
            expected_progress="loop_guard_stop",
            reason_code="no_progress_loop_detected",
            user_message="连续决策没有产生新进展，任务已停止。",
        )
    state.control_decision = decision
    state.add_event("executive_decision", {
        "turn": state.executive_turn,
        "decision": decision.model_dump(mode="json"),
        "semantic_hash": semantic_hash,
    })
    return {
        "control_decision": state.control_decision,
        "frontier_decision": state.frontier_decision,
        "selected_plan_step_ids": state.selected_plan_step_ids,
        "plan_ledger": state.plan_ledger,
        "executive_turn": state.executive_turn,
        "last_decision_hash": state.last_decision_hash,
        "repeated_decision_count": state.repeated_decision_count,
        "events": state.events,
    }


def _node_validate_decision(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.task_spec is None or state.execution_ledger is None or state.control_decision is None:
        raise RuntimeError("decision validation requires task, ledger, and decision")
    try:
        deps.decision_validator.validate(
            state.task_spec,
            state.execution_ledger,
            state.control_decision,
            state.control_state,
        )
        state.add_event("decision_validated", {
            "turn": state.executive_turn,
            "action": state.control_decision.action,
        })
    except Exception as exc:
        from personal_agent.kernel.contracts.executive import DecisionBasis

        state.add_event("decision_rejected", {
            "turn": state.executive_turn,
            "action": state.control_decision.action,
            "error": str(exc),
        })
        state.control_decision = StopDecision(
            target_goal_id=state.control_decision.target_goal_id,
            basis=DecisionBasis(
                expected_state_change="task_stopped",
                rejected_action_codes=("decision_validation_failed",),
            ),
            expected_progress="safe_stop",
            reason_code="decision_validation_failed",
            user_message=f"执行决策未通过确定性校验：{exc}",
        )
    return {"control_decision": state.control_decision, "events": state.events}


def _node_apply_decision(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    decision = state.control_decision
    if decision is None or state.execution_ledger is None or state.task_spec is None:
        raise RuntimeError("cannot apply an empty executive decision")
    state.current_action = None
    state.current_action_outcome = None
    state.step_execution = StepExecutionState()

    if isinstance(decision, ActivateSkillDecision):
        skill = deps.controller.skills.get(deps.controller.tenant_id, decision.skill_id)
        _append_execution_event(state, deps, "skill_activated", goal_id=decision.target_goal_id, payload={
            "skill_id": skill.manifest.skill_id,
            "version": skill.manifest.version,
        })
        state.context_envelope = state.context_envelope.model_copy(update={
            "active_skill_ids": state.execution_ledger.active_skill_ids,
        })
        state.add_event("skill_activated", {
            "skill_id": skill.manifest.skill_id,
            "version": skill.manifest.version,
        })
        return _route_update(state, "loop")

    if isinstance(decision, ExecuteMetaCapabilityDecision):
        state.current_action = decision.bounded_action
        state.current_actions = [decision.bounded_action]
        if state.selected_plan_step_ids and state.plan_ledger.plan is not None:
            state.plan_ledger = deps.plan_ledger_projector.append(
                state.plan_ledger,
                "step_running",
                step_ids=tuple(state.selected_plan_step_ids),
            )
        steps = _steps_for_action(state, decision.bounded_action)
        state.step_execution = StepExecutionState(
            steps=[StepRunState.from_execution_step(step) for step in steps],
        )
        state.add_event("action_materialized", {
            "action": state.current_action.model_dump(mode="json"),
            "step_count": len(steps),
        })
        update = _route_update(state, "action")
        update["plan_ledger"] = state.plan_ledger
        return update

    if isinstance(decision, DelegateDecision):
        action, step, gap = _materialize_delegate(state, deps, decision)
        if gap is not None:
            state.latest_observations.append(gap)
            _append_execution_event(state, deps, "goal_blocked", goal_id=decision.target_goal_id, payload={
                "evidence_gaps": (gap.requirement_id,),
            })
            state.add_event("capability_gap", gap.model_dump(mode="json"))
            return _route_update(state, "loop")
        state.current_action = action
        state.current_actions = [action]
        state.step_execution = StepExecutionState(steps=[StepRunState.from_execution_step(step)])
        state.add_event("action_materialized", {
            "action": action.model_dump(mode="json"),
            "step_count": 1,
        })
        return _route_update(state, "action")

    if isinstance(decision, InvokeProcedureDecision):
        materialized = deps.procedure_runtime.start(
            decision.procedure_call,
            task_id=state.task_spec.task_id,
        )
        state.current_action = BoundedAction(
            action_id=decision.procedure_call.procedure_call_id,
            goal_id=decision.target_goal_id,
            meta_capability="commit" if state.task_spec.mutation_intent else "acquire",
            description=f"procedure:{decision.procedure_call.procedure_id}",
            output_contract="ProcedureOutcome",
            proposed_resource_access=ProposedResourceAccessPlan(
                side_effect_class="procedure",
                write_set=({
                    "semantic_domain": "procedure",
                    "locator": decision.procedure_call.procedure_id,
                },),
            ),
            payload={
                "procedure_id": decision.procedure_call.procedure_id,
                "procedure_run_id": materialized.instance.procedure_run_id,
            },
        )
        state.current_actions = [state.current_action]
        state.procedure_id = decision.procedure_call.procedure_id
        state.procedure_version = decision.procedure_call.procedure_version
        state.active_procedure = materialized.instance
        state.step_execution = StepExecutionState(
            steps=[StepRunState.from_execution_step(step) for step in materialized.steps],
        )
        state.add_event("procedure_started", {
            "procedure_call": decision.procedure_call.model_dump(mode="json"),
            "procedure_run_id": materialized.instance.procedure_run_id,
            "step_count": len(materialized.steps),
        })
        return _route_update(state, "action")

    if isinstance(decision, ClarifyDecision):
        response = interrupt({
            "kind": "clarification",
            "question": decision.question,
            "task_id": state.task_spec.task_id,
        })
        observation = ObservationRef(
            goal_id=decision.target_goal_id,
            kind="user_clarification",
            provenance="user",
            summary=str(response),
            payload={"response": response},
        )
        state.latest_observations.append(observation)
        return _route_update(state, "loop")

    if isinstance(decision, RequestConfirmationDecision):
        response = interrupt({
            "kind": "confirmation",
            "title": decision.title,
            "summary": decision.summary,
            "task_id": state.task_spec.task_id,
        })
        observation = ObservationRef(
            goal_id=decision.target_goal_id,
            kind="user_confirmation",
            provenance="user",
            summary=str(response),
            payload={"response": response},
        )
        state.latest_observations.append(observation)
        return _route_update(state, "loop")

    if isinstance(decision, FinishDecision):
        return _route_update(state, "completion")

    if isinstance(decision, StopDecision):
        state.answer = state.answer or decision.user_message
        state.task_spec = state.task_spec.model_copy(update={"lifecycle": "stopped"})
        state.answer_completed = True
        _append_execution_event(state, deps, "task_stopped", payload={"reason_code": decision.reason_code})
        return _route_update(state, "stop")

    raise RuntimeError(f"unsupported executive decision: {decision.action}")


def _node_resolve_action(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.task_spec is None or state.execution_ledger is None or not state.current_actions:
        raise RuntimeError("action resolution requires materialized actions")
    projection = deps.context_manager.project(
        _context_items(state),
        purpose="action_execution",
        budget=_context_budget(state),
        ledger_revision=state.execution_ledger.revision,
        event_cursor=str(state.execution_ledger.last_event_sequence),
    )
    state.context_projections.append(projection)
    registry = build_capability_registry(
        tools=deps.tool_executor.list_tools(exposures={"public_agent", "scoped_agent", "admin"}),
        agents=deps.agent_gateway.profiles(),
    )
    specs = []
    for action in state.current_actions:
        resolution = None
        if action.requirement is not None and action.requirement.operations:
            resolution = CapabilityResolver(
                registry,
                policy_engine=deps.policy_engine,
                ranker=deps.capability_ranker,
            ).resolve(
                CapabilityResolutionRequest(
                    task_id=state.task_spec.task_id,
                    goal_id=action.goal_id,
                    action_id=action.action_id,
                    meta_capability=action.meta_capability,
                    allowed_kinds=("agent",) if "delegate" in action.requirement.operations else (
                        "local_tool", "mcp_tool", "retriever",
                    ),
                    allowed_operations=action.requirement.operations,
                    requirements=(action.requirement,),
                    policy=CapabilitySelectionPolicy(
                        read_only=action.proposed_resource_access.side_effect_class == "none",
                    ),
                )
            )
        access = deps.resource_access_resolver.resolve(
            action.proposed_resource_access,
            runtime_preflight=action.proposed_resource_access,
            preflight_complete=(
                action.proposed_resource_access.side_effect_class == "none"
                or bool(action.proposed_resource_access.write_set)
            ),
        )
        spec = deps.action_builder.build(
            decision_ref=_decision_semantic_hash(state.control_decision),
            action=action,
            context_projection_ref=projection.projection_id,
            access_plan=access,
            capability_resolution=resolution,
            retry_directive=state.retry_directive,
        )
        deps.scheduler.validate_dispatch(spec)
        specs.append(spec)
        matching_steps = [
            step for step in state.step_execution.steps
            if step.step_id == action.action_id or step.task_id == action.goal_id
        ]
        if resolution is not None:
            state.add_event("capability_resolution", {
                "resolution_id": resolution.resolution_id,
                "scope_id": resolution.request.scope_id,
                "goal_id": resolution.request.goal_id,
                "action_id": resolution.request.action_id,
                "selected_capability_ids": [
                    item.capability_id for item in resolution.selected_capabilities
                ],
                "allowed_tools": list(resolution.allowed_tools),
                "allowed_agents": list(resolution.allowed_agents),
                "coverage": [item.model_dump(mode="json") for item in resolution.coverage],
            })
            for step in matching_steps:
                step.allowed_tools = list(resolution.allowed_tools)
                if (
                    step.execution_mode != "react"
                    and step.action_type == "tool_call"
                    and not step.tool_name
                    and resolution.allowed_tools
                ):
                    step.tool_name = resolution.allowed_tools[0]
                if resolution.allowed_agents and not step.agent_id:
                    step.agent_id = resolution.allowed_agents[0]
    state.resolved_action_specs = specs
    state.resolved_action_spec = specs[0]
    state.dispatch_groups = list(deps.scheduler.create_dispatch_groups(
        tuple(specs),
        requested_join_policy=(
            state.frontier_decision.requested_join_policy
            if state.frontier_decision is not None else "all"
        ),
    ))
    if state.plan_ledger.plan is not None and state.selected_plan_step_ids:
        state.plan_ledger = deps.plan_ledger_projector.append(
            state.plan_ledger,
            "dispatch_grouped",
            step_ids=tuple(state.selected_plan_step_ids),
            payload={
                "dispatch_groups": [
                    item.model_dump(mode="json") for item in state.dispatch_groups
                ],
            },
        )
    state.add_event("action_resolved", {
        "action_specs": [item.model_dump(mode="json") for item in specs],
        "context_projection": projection.model_dump(mode="json"),
    })
    return {
        "resolved_action_spec": state.resolved_action_spec,
        "resolved_action_specs": state.resolved_action_specs,
        "dispatch_groups": state.dispatch_groups,
        "plan_ledger": state.plan_ledger,
        "context_projections": state.context_projections,
        "step_execution": state.step_execution,
        "events": state.events,
    }


def _node_observe_action(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.current_action is None or state.execution_ledger is None:
        return _route_update(state, "loop")
    state.control_route = "verify"
    state.retry_directive = None
    statuses = [step.status for step in state.step_execution.steps]
    failed = next((step for step in state.step_execution.steps if step.status == "failed"), None)
    if failed is not None:
        summary = failed.failure_reason or "bounded action failed"
        if state.active_procedure is not None:
            state.active_procedure = state.active_procedure.model_copy(update={
                "status": "failed",
            })
        classification = classify_failure(summary)
        goal = next(
            (item for item in state.execution_ledger.items if item.goal_id == state.current_action.goal_id),
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
                provenance="capability_resolver",
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
                    "meta_capability": state.current_action.meta_capability,
                    "retryable": False,
                    "error_code": "capability_gap",
                    "resolvable_by_resource_binding": not first.resource_bound,
                    "resolvable_by_authorization": classification.error_code == "authorization_required",
                },
            )
            state.add_event("capability_gap", observation.model_dump(mode="json"))
        elif (
            state.current_action.payload.get("procedure_id")
            and failed.procedure_recovery_policy == "clarify"
        ):
            observation = ObservationRef(
                goal_id=state.current_action.goal_id,
                kind="procedure_clarification",
                provenance=str(state.current_action.payload["procedure_id"]),
                summary=summary,
                payload={
                    "procedure_id": state.current_action.payload["procedure_id"],
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
                    "meta_capability": state.current_action.meta_capability,
                },
            )
        state.latest_observations.append(observation)
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
                meta_capability=state.current_action.meta_capability,
                status="failed",
            ).model_dump(mode="json"),
        })
        for spec in state.resolved_action_specs:
            if spec.goal_id != state.current_action.goal_id:
                continue
            for capability_id in spec.capability_refs:
                deps.capability_ranker.store.record(
                    capability_id,
                    succeeded=False,
                    verifier_passed=False,
                    latency_ms=0.0,
                )
        attempt_count = 1 + sum(
            item.meta_capability == state.current_action.meta_capability
            for item in (goal.attempts if goal is not None else ())
        )
        state.retry_directive = deps.recovery_policy.directive(
            observation,
            requirement_id=(
                state.current_action.requirement.requirement_id
                if state.current_action.requirement else state.current_action.action_id
            ),
            idempotency_key=f"{state.task_spec.task_id}:{state.current_action.action_id}:{attempt_count}",
            attempt_count=attempt_count,
            max_attempts=2,
            action_idempotent=(
                state.current_action.proposed_resource_access.side_effect_class == "none"
            ),
            failed_provider_id=str(observation.payload.get("provider_id", "")),
        )
        if state.retry_directive.retry_kind != "none":
            failed.status = "planned"
            state.control_route = "technical_retry"
            state.add_event("retry_directive_issued", state.retry_directive.model_dump(mode="json"))
        else:
            _append_execution_event(state, deps, "goal_blocked", goal_id=state.current_action.goal_id, payload={
                "evidence_gaps": tuple(
                    f"{item.requirement_id}: {item.rationale}" for item in incomplete
                ) or (classification.error_code,),
            })
            state.control_route = "verify"
        if state.current_action.payload.get("procedure_id"):
            state.add_event("procedure_failed", {
                "procedure_id": state.current_action.payload["procedure_id"],
                "procedure_run_id": state.current_action.payload.get("procedure_run_id"),
                "procedure_node_id": failed.procedure_node_id,
                "recovery_policy": failed.procedure_recovery_policy,
                "error": summary,
            })
        state.errors = []
    elif state.pending_confirmation is not None or any(status == "awaiting_confirmation" for status in statuses):
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
            step.output_artifact_id for step in state.step_execution.steps if step.output_artifact_id
        )
        observation = ObservationRef(
            goal_id=state.current_action.goal_id,
            kind="action_result",
            provenance="executor",
            summary=_action_summary(state),
            payload={
                "action_id": state.current_action.action_id,
                "meta_capability": state.current_action.meta_capability,
                "step_ids": [step.step_id for step in state.step_execution.steps],
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
        _append_execution_event(state, deps, "attempt_recorded", goal_id=state.current_action.goal_id, payload={
            "attempt": AttemptRef(
                action_id=state.current_action.action_id,
                meta_capability=state.current_action.meta_capability,
                status="succeeded",
                artifact_ids=result_keys,
            ).model_dump(mode="json"),
        })
        for additional in state.current_actions[1:]:
            additional_step = next(
                (step for step in state.step_execution.steps if step.step_id == additional.action_id),
                None,
            )
            if additional_step is None or additional_step.status != "completed":
                continue
            _append_execution_event(state, deps, "attempt_recorded", goal_id=additional.goal_id, payload={
                "attempt": AttemptRef(
                    action_id=additional.action_id,
                    meta_capability=additional.meta_capability,
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
        if state.current_action.payload.get("procedure_id"):
            from personal_agent.kernel.contracts.agentic import ContextItem

            receipt_items = []
            for result in state.step_execution.results.values():
                if not isinstance(result, dict) or not result.get("note_id"):
                    continue
                note_id = str(result["note_id"])
                receipt_items.append(ContextItem(
                    ref_id=note_id,
                    kind="mutation_receipt",
                    provenance=str(state.current_action.payload["procedure_id"]),
                    trust_tier="evidence",
                    summary=str(result.get("summary") or result.get("title") or "")[:1000],
                    payload={
                        "note_id": note_id,
                        "title": str(result.get("title") or ""),
                        "summary": str(result.get("summary") or ""),
                    },
                    admitted=True,
                ))
            if receipt_items and state.context_envelope is not None:
                existing_refs = {
                    item.ref_id for item in state.context_envelope.evidence_context
                }
                unique_receipts = {
                    item.ref_id: item for item in receipt_items
                    if item.ref_id not in existing_refs
                }
                receipt_items = list(unique_receipts.values())
                state.context_envelope = state.context_envelope.model_copy(update={
                    "evidence_context": (
                        *state.context_envelope.evidence_context,
                        *receipt_items,
                    ),
                })
                state.add_event("context_admitted", {
                    "trust_tier": "evidence",
                    "count": len(receipt_items),
                    "source": "mutation_receipt",
                    "admitted_as_instruction": False,
                })
            state.add_event("procedure_completed", {
                "procedure_id": state.current_action.payload["procedure_id"],
                "procedure_run_id": state.current_action.payload.get("procedure_run_id"),
                "goal_id": state.current_action.goal_id,
            })
    state.current_action_outcome = outcome
    if outcome.observation is not None and outcome.observation not in state.latest_observations:
        state.latest_observations.append(outcome.observation)
    state.add_event("action_outcome", outcome.model_dump(mode="json"))
    return {
        "current_action_outcome": state.current_action_outcome,
        "retry_directive": state.retry_directive,
        "control_route": state.control_route,
        "latest_observations": state.latest_observations,
        "execution_ledger": state.execution_ledger,
        "execution_events": state.execution_events,
        "context_envelope": state.context_envelope,
        "active_procedure": state.active_procedure,
        "errors": state.errors,
        "events": state.events,
    }


def _node_verify_goal_progress(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.task_spec is None or state.execution_ledger is None:
        return {}
    candidates = [item for item in state.execution_ledger.items if item.status == "candidate_complete"]
    for goal in candidates:
        verification_results = _goal_scoped_verification_results(state, goal.goal_id)
        evidence_refs = tuple(dict.fromkeys(
            artifact_id
            for attempt in goal.attempts
            for artifact_id in attempt.artifact_ids
            if artifact_id
        ))
        verifier_profiles = _verifier_profiles(state, deps, goal)
        verification_items = _verification_context_items(
            state,
            goal,
            verification_results,
            evidence_refs,
            verifier_profiles,
        )
        projection = deps.context_manager.project(
            verification_items,
            purpose="semantic_verification",
            budget=_context_budget(state),
            ledger_revision=state.execution_ledger.revision,
            event_cursor=str(state.execution_ledger.last_event_sequence),
        )
        state.context_projections.append(projection)
        materialized = deps.context_gateway.open(
            projection, verification_items, purpose="semantic_verification",
        )
        semantic_context = None
        if (
            deps.goal_verifier.semantic_enabled
            and state.planning_budget.semantic_verifier_calls
            < state.planning_budget.max_semantic_verifier_calls
        ):
            semantic_context = materialized.model_payload()
            state.planning_budget = state.planning_budget.model_copy(update={
                "semantic_verifier_calls": state.planning_budget.semantic_verifier_calls + 1,
            })
        report = deps.goal_verifier.verify(
            state.task_spec,
            goal,
            answer=state.answer,
            citation_count=len(state.citations) if len(state.execution_ledger.items) == 1 else 0,
            tool_results=tuple(verification_results),
            evidence_refs=evidence_refs,
            model_context=semantic_context,
        )
        _append_execution_event(state, deps, "verification_recorded", goal_id=goal.goal_id, payload={
            "verification": report.model_dump(mode="json"),
        })
        if report.status == "passed":
            _append_execution_event(state, deps, "goal_verified", goal_id=goal.goal_id, payload={
                "verification": report.model_dump(mode="json"),
                "evidence_gaps": (),
            })
        else:
            _append_execution_event(state, deps, "goal_activated", goal_id=goal.goal_id, payload={
                "verification": report.model_dump(mode="json"),
                "evidence_gaps": report.unresolved_gaps,
            })
            state.latest_observations.append(ObservationRef(
                goal_id=goal.goal_id,
                kind="verification_gap",
                provenance="goal_verifier",
                summary="; ".join(report.unresolved_gaps) or "goal verification did not pass",
                payload={
                    "gap_ids": list(report.unresolved_gaps),
                    "recommended_next_actions": list(report.recommended_next_actions),
                },
            ))
        state.add_event("goal_verification", report.model_dump(mode="json"))
        for spec in state.resolved_action_specs:
            if spec.goal_id != goal.goal_id:
                continue
            for capability_id in spec.capability_refs:
                deps.capability_ranker.store.record(
                    capability_id,
                    succeeded=True,
                    verifier_passed=report.status == "passed",
                    latency_ms=0.0,
                )
    if state.control_route == "direct_candidate":
        if state.execution_ledger.items and all(
            item.status == "verified" for item in state.execution_ledger.items
        ):
            state.control_decision = FinishDecision(
                target_goal_id=state.execution_ledger.items[-1].goal_id,
                basis=DecisionBasis(expected_state_change="task_completed"),
                expected_progress="verified_direct_completion",
                completion_claim=CompletionClaim(
                    goal_ids=tuple(item.goal_id for item in state.execution_ledger.items),
                    criterion_ids=tuple(
                        item.criterion_id for item in state.task_spec.success_criteria
                    ),
                ),
            )
            state.control_route = "direct_completion"
        else:
            state.control_route = "loop"
    return {
        "execution_ledger": state.execution_ledger,
        "execution_events": state.execution_events,
        "events": state.events,
        "control_decision": state.control_decision,
        "control_route": state.control_route,
        "latest_observations": state.latest_observations,
        "planning_budget": state.planning_budget,
        "context_projections": state.context_projections,
    }


def _goal_scoped_verification_results(
    state: AgentGraphState,
    goal_id: str,
) -> list[dict]:
    goal_step_ids = {
        item.step_id for item in state.step_execution.steps if item.task_id == goal_id
    }
    results = [
        item for item in state.tool_results
        if isinstance(item, dict)
        and (item.get("_goal_id") == goal_id or item.get("_step_id") in goal_step_ids)
    ]
    results.extend(
        item for step_id, item in state.step_execution.results.items()
        if step_id in goal_step_ids and isinstance(item, dict)
    )
    return results


def _node_verify_completion(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.task_spec is None or state.execution_ledger is None:
        raise RuntimeError("completion verification requires task and ledger")
    claim = state.control_decision.completion_claim if isinstance(state.control_decision, FinishDecision) else None
    report = deps.completion_verifier.verify(
        state.task_spec,
        state.execution_ledger,
        claim,
        pending_confirmation=state.pending_confirmation is not None,
    )
    state.completion_report = report
    state.add_event("completion_checked", report.model_dump(mode="json"))
    if report.status == "complete":
        state.task_spec = state.task_spec.model_copy(update={"lifecycle": "completed"})
        state.answer_completed = True
        _append_execution_event(state, deps, "task_completed", payload={
            "verified_goal_ids": report.verified_goal_ids,
        })
    else:
        observation = ObservationRef(
            kind="completion_gap",
            provenance="completion_verifier",
            summary=", ".join(report.reason_codes) or "completion rejected",
            payload=report.model_dump(mode="json"),
        )
        state.latest_observations.append(observation)
        _append_execution_event(state, deps, "completion_rejected", payload=report.model_dump(mode="json"))
        state.add_event("completion_rejected", report.model_dump(mode="json"))
    return {
        "task_spec": state.task_spec,
        "procedure_id": state.procedure_id,
        "procedure_version": state.procedure_version,
        "active_procedure": state.active_procedure,
        "completion_report": state.completion_report,
        "answer_completed": state.answer_completed,
        "latest_observations": state.latest_observations,
        "execution_ledger": state.execution_ledger,
        "execution_events": state.execution_events,
        "events": state.events,
    }


def _verifier_profiles(
    state: AgentGraphState,
    deps: ExecutiveContext,
    goal,
) -> tuple[str, ...]:
    profiles = []
    if state.execution_ledger is None or state.task_spec is None:
        return ()
    domains = {
        item.semantic_domain
        for item in state.task_spec.resource_requirements
        if item.goal_id == goal.goal_id
    }
    for skill_id in state.execution_ledger.active_skill_ids:
        try:
            skill = deps.controller.skills.get(deps.controller.tenant_id, skill_id)
        except (KeyError, PermissionError):
            continue
        if (
            domains.intersection(skill.manifest.applicability.semantic_domains)
            or state.task_spec.result_contract in skill.manifest.applicability.result_contracts
        ):
            profiles.append(skill.manifest.verifier_profile)
    return tuple(dict.fromkeys(item for item in profiles if item))


def _after_apply_decision(state: AgentGraphState) -> str:
    return state.control_route or "loop"


def _after_completion(state: AgentGraphState) -> str:
    if state.completion_report and state.completion_report.status == "complete":
        return "complete"
    return "loop"


def _route_update(state: AgentGraphState, route: str) -> dict:
    state.control_route = route
    return {
        "control_route": state.control_route,
        "current_action": state.current_action,
        "current_actions": state.current_actions,
        "current_action_outcome": state.current_action_outcome,
        "step_execution": state.step_execution,
        "execution_ledger": state.execution_ledger,
        "execution_events": state.execution_events,
        "context_envelope": state.context_envelope,
        "latest_observations": state.latest_observations,
        "task_spec": state.task_spec,
        "procedure_id": state.procedure_id,
        "procedure_version": state.procedure_version,
        "active_procedure": state.active_procedure,
        "answer": state.answer,
        "answer_completed": state.answer_completed,
        "events": state.events,
    }


def _step_for_action(state: AgentGraphState, action: BoundedAction) -> ExecutionStep:
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
    }.get(action.meta_capability, "compose")
    use_agentic_synthesis = bool(action.payload.get("agentic_synthesis"))
    execution_mode = "react" if (
        action.meta_capability == "explore"
        or (action.meta_capability == "acquire" and external_acquire)
        or (
            action.meta_capability in {"reason", "transform"}
            and use_agentic_synthesis
        )
    ) else "deterministic"
    requirements = []
    if action.requirement is not None:
        requirements = [action.requirement.model_dump(mode="json")]
    return ExecutionStep(
        step_id=action.action_id,
        action_type=action_type,
        description=action.description,
        expected_output=action.output_contract,
        success_criteria="produce the declared output contract",
        risk_level="medium" if action.meta_capability == "commit" else "low",
        requires_confirmation=action.meta_capability == "commit",
        on_failure="retry",
        execution_mode=execution_mode,
        max_iterations=action.max_iterations,
        projection_kind="bounded_action",
        task_id=action.goal_id,
        task_input=action.payload.get("task_text", action.description),
        meta_capability=action.meta_capability,
        output_contract=action.output_contract,
        capability_requirements=requirements,
        skill_ids=list(state.execution_ledger.active_skill_ids) if state.execution_ledger else [],
        execution_guidance=list(action.payload.get("execution_guidance", ())),
    )


def _steps_for_action(
    state: AgentGraphState,
    action: BoundedAction,
) -> tuple[ExecutionStep, ...]:
    commit = _step_for_action(state, action)
    if action.meta_capability != "commit":
        return (commit,)
    proposal = ExecutionStep(
        step_id=f"{action.action_id}:proposal",
        action_type="resolve",
        description=f"Propose a scoped mutation for: {action.description}",
        expected_output="ProposedCommit",
        success_criteria="return a supported proposed_commit or explicitly decline",
        execution_mode="react",
        max_iterations=action.max_iterations,
        projection_kind="bounded_action",
        task_id=action.goal_id,
        task_input=action.payload.get("task_text", action.description),
        meta_capability="explore",
        output_contract="ProposedCommit",
        skill_ids=list(state.execution_ledger.active_skill_ids) if state.execution_ledger else [],
        execution_guidance=list(action.payload.get("execution_guidance", ())),
    )
    commit.depends_on = [proposal.step_id]
    commit.execution_mode = "deterministic"
    return proposal, commit


def _materialize_delegate(
    state: AgentGraphState,
    deps: ExecutiveContext,
    decision: DelegateDecision,
) -> tuple[BoundedAction, ExecutionStep, CapabilityGapObservation | None]:
    requirement = decision.subtask.required_capability
    registry = build_capability_registry(agents=deps.agent_gateway.profiles())
    resolution = CapabilityResolver(
        registry,
        policy_engine=deps.policy_engine,
        ranker=deps.capability_ranker,
    ).resolve(
        CapabilityResolutionRequest(
            task_id=state.task_spec.task_id if state.task_spec else "",
            goal_id=decision.target_goal_id,
            action_id=decision.subtask.subtask_id,
            meta_capability="delegate",
            allowed_kinds=("agent",),
            allowed_operations=("delegate",),
            requirements=(requirement,),
            policy=CapabilitySelectionPolicy(read_only=True),
        )
    )
    if not resolution.allowed_agents or any(item.status != "satisfied" for item in resolution.coverage):
        coverage = resolution.coverage[0] if resolution.coverage else None
        gap = CapabilityGapObservation(
            goal_id=decision.target_goal_id,
            provenance="capability_resolver",
            summary=coverage.rationale if coverage else "no agent capability available",
            requirement_id=requirement.requirement_id,
            status=coverage.status if coverage and coverage.status != "satisfied" else "unavailable",
            missing_operations=tuple(coverage.missing_operations) if coverage else tuple(requirement.operations),
            attempted_capability_classes=("agent",),
            suggested_capability_classes=("local_tool", "mcp_tool"),
        )
        empty_action = BoundedAction(
            goal_id=decision.target_goal_id,
            meta_capability="delegate",
            description=decision.subtask.goal,
            output_contract=decision.subtask.expected_artifact_contract,
            requirement=requirement,
        )
        return empty_action, ExecutionStep(), gap
    agent_id = resolution.allowed_agents[0]
    profile = deps.agent_gateway.profile(agent_id)
    if profile is None:
        raise RuntimeError("resolved subagent profile disappeared")
    selected_ids = tuple(item.capability_id for item in resolution.selected_capabilities)
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
            state.task_spec.constraints.token_budget
            if state.task_spec and state.task_spec.constraints.token_budget
            else decision.subtask.token_budget
        ),
        parent_cost_remaining=decision.subtask.cost_budget,
        parent_time_remaining=decision.subtask.time_budget_seconds,
    )
    action = BoundedAction(
        action_id=decision.subtask.subtask_id,
        goal_id=decision.target_goal_id,
        meta_capability="delegate",
        description=decision.subtask.goal,
        output_contract="AgentArtifact",
        requirement=requirement,
        max_tool_calls=decision.subtask.max_provider_calls,
        max_model_calls=0,
        payload={
            "task_text": decision.subtask.goal,
            "agent_id": agent_id,
            "effective_scope": {
                "capability_ids": effective_scope.capability_ids,
                "operations": effective_scope.operations,
            },
            "budget_reservation": {
                "token_budget": reservation.token_budget,
                "cost_budget": reservation.cost_budget,
                "time_budget_seconds": reservation.time_budget_seconds,
            },
        },
    )
    step = _step_for_action(state, action)
    step.agent_id = agent_id
    step.subtask_spec = {
        "goal": decision.subtask.goal,
        "verification_policy": decision.subtask.verification_policy,
        "expected_artifact_contract": decision.subtask.expected_artifact_contract,
        "max_provider_calls": decision.subtask.max_provider_calls,
    }
    step.capability_requirements = [requirement.model_dump(mode="json")]
    return action, step, None


def _action_summary(state: AgentGraphState) -> str:
    results = [
        value for value in state.step_execution.results.values()
        if value is not None
    ]
    for result in reversed(results):
        if isinstance(result, dict) and result.get("answer"):
            return str(result["answer"])[:1500]
    if state.answer:
        return state.answer[:1500]
    return str(results[-1])[:1500] if results else "action completed"


def _action_closes_goal(state: AgentGraphState, action: BoundedAction) -> bool:
    if action.payload.get("procedure_id"):
        return True
    if state.execution_ledger is None:
        return False
    goal = next(
        (item for item in state.execution_ledger.items if item.goal_id == action.goal_id),
        None,
    )
    if goal is None:
        return False
    return action.output_contract == goal.output_contract


def _context_items(state: AgentGraphState):
    envelope = state.context_envelope
    items = (
        *envelope.run_context,
        *envelope.working_memory,
        *envelope.trusted_memory,
        *envelope.evidence_context,
        *envelope.untrusted_observations,
    )
    priority = {"runtime": 0, "trusted": 1, "evidence": 2, "working": 3, "untrusted": 4}
    by_ref: dict[str, ContextItem] = {}
    for item in items:
        current = by_ref.get(item.ref_id)
        if current is None or priority[item.trust_tier] < priority[current.trust_tier]:
            by_ref[item.ref_id] = item
    return tuple(by_ref.values())


def _planning_context_items(state: AgentGraphState, procedures) -> tuple[ContextItem, ...]:
    if state.task_spec is None or state.execution_ledger is None:
        return _context_items(state)
    runtime = ContextItem(
        ref_id=(
            f"planning:{state.task_spec.task_id}:{state.task_spec.revision}:"
            f"{state.execution_ledger.goal_graph_revision}"
        ),
        kind="planning_state",
        provenance="runtime",
        trust_tier="runtime",
        summary=state.task_spec.user_goal,
        payload={
            "task": state.task_spec.model_dump(mode="json"),
            "goal_graph": [item.model_dump(mode="json") for item in state.execution_ledger.items],
            "procedures": [
                item.model_dump(mode="json") for item in procedures
                if item.status in {"eligible", "mandatory"}
            ],
            "budget": state.planning_budget.model_dump(mode="json"),
            "active_plan": (
                state.plan_ledger.plan.model_dump(mode="json")
                if state.plan_ledger.plan is not None else None
            ),
            "plan_step_statuses": state.plan_ledger.step_statuses,
            "replan_request": (
                state.replan_request.model_dump(mode="json")
                if state.replan_request is not None else None
            ),
        },
        admitted=True,
    )
    observations = tuple(ContextItem(
        ref_id=f"observation:{item.observation_id}",
        kind="observation",
        provenance=item.provenance,
        trust_tier="untrusted",
        summary=item.summary,
        payload=item.model_dump(mode="json"),
        admitted=False,
    ) for item in state.latest_observations[-8:])
    return (*_context_items(state), runtime, *observations)


def _monitor_context_items(state: AgentGraphState) -> tuple[ContextItem, ...]:
    if state.task_spec is None or state.execution_ledger is None:
        return _context_items(state)
    runtime = ContextItem(
        ref_id=f"monitor:{state.task_spec.task_id}:{state.plan_ledger.last_event_sequence}",
        kind="plan_monitor_state",
        provenance="runtime",
        trust_tier="runtime",
        summary=state.task_spec.user_goal,
        payload={
            "task_revision": state.task_spec.revision,
            "goal_graph_revision": state.execution_ledger.goal_graph_revision,
            "active_plan": (
                state.plan_ledger.plan.model_dump(mode="json")
                if state.plan_ledger.plan is not None else None
            ),
            "step_statuses": state.plan_ledger.step_statuses,
            "selected_step_ids": tuple(state.selected_plan_step_ids),
            "authority_tier": "system_policy",
        },
        admitted=True,
    )
    observations = tuple(ContextItem(
        ref_id=f"monitor-observation:{item.observation_id}",
        kind="observation",
        provenance=item.provenance,
        trust_tier="untrusted",
        summary=item.summary,
        payload=item.model_dump(mode="json"),
        admitted=False,
    ) for item in state.latest_observations[-6:])
    return (*_context_items(state), runtime, *observations)


def _verification_context_items(
    state: AgentGraphState,
    goal,
    tool_results: list[dict],
    evidence_refs: tuple[str, ...],
    verifier_profiles: tuple[str, ...],
) -> tuple[ContextItem, ...]:
    assert state.task_spec is not None
    criteria = tuple(
        item.model_dump(mode="json")
        for item in state.task_spec.success_criteria
        if item.criterion_id in goal.success_criterion_ids
    )
    runtime = ContextItem(
        ref_id=f"verification:{state.task_spec.task_id}:{goal.goal_id}",
        kind="verification_contract",
        provenance="runtime",
        trust_tier="runtime",
        summary=goal.description,
        payload={
            "goal": goal.description,
            "criteria": criteria,
            "evidence_refs": evidence_refs,
            "verifier_profiles": verifier_profiles,
            "authority_tier": "system_policy",
        },
        admitted=True,
    )
    answer = ContextItem(
        ref_id=f"verification-answer:{goal.goal_id}",
        kind="candidate_answer",
        provenance="agent_runtime",
        trust_tier="untrusted",
        summary=(state.answer or "")[:2000],
        payload={"answer": (state.answer or "")[:12000]},
        admitted=False,
    )
    evidence = tuple(ContextItem(
        ref_id=f"verification-evidence:{goal.goal_id}:{index}",
        kind="goal_evidence",
        provenance="action_execution",
        trust_tier="untrusted",
        summary=_safe_context_summary(item),
        payload={"evidence": item},
        admitted=False,
    ) for index, item in enumerate(tool_results[:8]))
    return (runtime, answer, *evidence)


def _safe_context_summary(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:2000]


def _control_context_items(state: AgentGraphState) -> tuple[ContextItem, ...]:
    if state.task_spec is None or state.execution_ledger is None or state.control_state is None:
        return _context_items(state)
    runtime = ContextItem(
        ref_id=(
            f"control:{state.task_spec.task_id}:{state.task_spec.revision}:"
            f"{state.execution_ledger.revision}"
        ),
        kind="control_state",
        provenance="runtime",
        trust_tier="runtime",
        summary=state.task_spec.user_goal,
        payload={
            "task": state.task_spec.model_dump(mode="json"),
            "goal_graph": [item.model_dump(mode="json") for item in state.execution_ledger.items],
            "control": state.control_state.model_dump(mode="json"),
        },
        admitted=True,
    )
    return (*_context_items(state), runtime)


def _context_budget(state: AgentGraphState) -> ContextBudget:
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
    if isinstance(decision, ExecuteMetaCapabilityDecision):
        payload["meta_capability"] = decision.bounded_action.meta_capability
        payload["requirement"] = (
            decision.bounded_action.requirement.purpose
            if decision.bounded_action.requirement else ""
        )
    elif isinstance(decision, InvokeProcedureDecision):
        payload["procedure_id"] = decision.procedure_call.procedure_id
    elif isinstance(decision, DelegateDecision):
        payload["subtask_goal"] = decision.subtask.goal
    elif isinstance(decision, ActivateSkillDecision):
        payload["skill_id"] = decision.skill_id
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:16]


__all__ = [
    "_after_apply_decision",
    "_after_completion",
    "_node_apply_decision",
    "_node_decide",
    "_node_compile_goal_graph",
    "_node_observe_action",
    "_node_project_control_state",
    "_node_resolve_action",
    "_node_validate_decision",
    "_node_verify_completion",
    "_node_verify_goal_progress",
]
