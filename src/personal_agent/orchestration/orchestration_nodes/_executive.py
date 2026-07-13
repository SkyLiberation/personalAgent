"""Nodes for the task-level executive control loop."""

from __future__ import annotations

from hashlib import sha256
import json
import logging

from langgraph.types import interrupt

from personal_agent.kernel.contracts.agentic import (
    AttemptRef,
    ExecutionLedger,
    PlanMacroRef,
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
    DelegateDecision,
    ExecuteMetaCapabilityDecision,
    ExecuteParallelDecision,
    FinishDecision,
    InvokeProtocolDecision,
    ObservationRef,
    RequestConfirmationDecision,
    RevisePlanDecision,
    StopDecision,
)
from personal_agent.orchestration.orchestration_contexts import ExecutiveContext
from personal_agent.orchestration.orchestration_models import AgentGraphState, StepExecutionState, StepRunState
from personal_agent.planning.capability_resolver import CapabilityResolver
from personal_agent.planning.ledger import next_execution_event
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


def _node_interpret_goal(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.router_decision is None:
        raise RuntimeError("semantic goal interpretation requires router output")
    interpretation = deps.goal_interpreter.interpret(state.router_decision, state.entry_text)
    state.task_spec = interpretation.task_spec
    state.context_envelope = interpretation.context_envelope
    state.execution_ledger = ExecutionLedger(task_id=interpretation.task_spec.task_id)
    _append_execution_event(state, deps, "task_created", payload={
        "task_spec": state.task_spec.model_dump(mode="json"),
    })
    for item in interpretation.ledger.items:
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
    state.add_event("goal_interpreted", {
        "task_id": state.task_spec.task_id,
        "revision": state.task_spec.revision,
        "goal_ids": [item.goal_id for item in state.execution_ledger.items],
    })
    return {
        "task_spec": state.task_spec,
        "execution_ledger": state.execution_ledger,
        "context_envelope": state.context_envelope,
        "execution_events": state.execution_events,
        "events": state.events,
        "executive_turn": state.executive_turn,
    }


def _node_project_control_state(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.task_spec is None or state.execution_ledger is None:
        raise RuntimeError("control state requires task and ledger")
    registry = build_capability_registry(
        tools=deps.tool_executor.list_tools(exposures={"public_agent", "scoped_agent", "admin"}),
        agents=deps.agent_gateway.definitions(),
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
    return {"control_state": state.control_state, "events": state.events}


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
        decision = deps.controller.decide(
            state.task_spec,
            state.execution_ledger,
            observations=tuple(state.latest_observations),
            capability_classes=state.control_state.available_capability_classes,
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
        "executive_turn": state.executive_turn,
        "last_decision_hash": state.last_decision_hash,
        "repeated_decision_count": state.repeated_decision_count,
        "events": state.events,
    }


def _node_validate_decision(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.task_spec is None or state.execution_ledger is None or state.control_decision is None:
        raise RuntimeError("decision validation requires task, ledger, and decision")
    try:
        deps.decision_validator.validate(state.task_spec, state.execution_ledger, state.control_decision)
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
        skill = deps.controller.skills.get(decision.skill_id)
        _append_execution_event(state, deps, "skill_activated", goal_id=decision.target_goal_id, payload={
            "skill_id": skill.skill_id,
            "version": skill.version,
        })
        state.context_envelope = state.context_envelope.model_copy(update={
            "active_skill_ids": state.execution_ledger.active_skill_ids,
        })
        state.add_event("skill_activated", {"skill_id": skill.skill_id, "version": skill.version})
        return _route_update(state, "loop")

    if isinstance(decision, RevisePlanDecision):
        deps.ledger_patch_validator.validate(state.execution_ledger, decision.proposed_ledger_patch)
        for operation in decision.proposed_ledger_patch.operations:
            if operation.op == "apply_macro":
                ref = PlanMacroRef(
                    macro_id=str(operation.values["macro_id"]),
                    version=str(operation.values.get("version", "v1")),
                    applied_revision=state.execution_ledger.revision,
                )
                _append_execution_event(state, deps, "macro_applied", goal_id=decision.target_goal_id, payload={
                    "macro": ref.model_dump(mode="json"),
                })
                state.add_event("macro_applied", ref.model_dump(mode="json"))
        return _route_update(state, "loop")

    if isinstance(decision, ExecuteMetaCapabilityDecision):
        state.current_action = decision.bounded_action
        state.current_actions = [decision.bounded_action]
        step = _step_for_action(state, decision.bounded_action)
        state.step_execution = StepExecutionState(steps=[StepRunState.from_execution_step(step)])
        state.add_event("action_materialized", {
            "action": state.current_action.model_dump(mode="json"),
            "step_count": 1,
        })
        return _route_update(state, "action")

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

    if isinstance(decision, ExecuteParallelDecision):
        # Read-only actions are materialized together; the executor may schedule
        # independent provider calls concurrently when their tool annotations allow it.
        steps = [_step_for_action(state, action) for action in decision.parallel_actions]
        state.step_execution = StepExecutionState(
            steps=[StepRunState.from_execution_step(step) for step in steps],
        )
        state.current_action = decision.parallel_actions[0] if decision.parallel_actions else None
        state.current_actions = list(decision.parallel_actions)
        state.add_event("action_materialized", {
            "parallel_action_ids": [item.action_id for item in decision.parallel_actions],
            "step_count": len(steps),
        })
        return _route_update(state, "action")

    if isinstance(decision, InvokeProtocolDecision):
        materialized = deps.protocol_registry.materialize(
            decision.protocol_call,
            entry_text=state.entry_text,
            routing_key=f"{state.user_id}:{state.session_id}",
        )
        state.current_action = BoundedAction(
            action_id=decision.protocol_call.protocol_call_id,
            goal_id=decision.target_goal_id,
            meta_capability="commit" if state.task_spec.mutation_intent else "acquire",
            description=f"protocol:{decision.protocol_call.protocol_id}",
            output_contract="ProtocolOutcome",
            side_effect_class="protocol",
            payload={"protocol_id": decision.protocol_call.protocol_id},
        )
        state.current_actions = [state.current_action]
        state.workflow_id = decision.protocol_call.protocol_id
        state.workflow_version = "protocol-v1"
        state.step_execution = StepExecutionState(
            steps=[StepRunState.from_execution_step(step) for step in materialized.steps],
        )
        state.add_event("protocol_started", {
            "protocol_call": decision.protocol_call.model_dump(mode="json"),
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


def _node_observe_action(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.current_action is None or state.execution_ledger is None:
        return _route_update(state, "loop")
    statuses = [step.status for step in state.step_execution.steps]
    failed = next((step for step in state.step_execution.steps if step.status == "failed"), None)
    if failed is not None:
        summary = failed.failure_reason or "bounded action failed"
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
                suggested_capability_classes=("mcp_tool", "agent"),
            )
            state.add_event("capability_gap", observation.model_dump(mode="json"))
        else:
            observation = ObservationRef(
                kind="action_failure",
                provenance="executor",
                summary=summary,
                payload={"action_id": state.current_action.action_id, "step_id": failed.step_id},
            )
        outcome = ActionOutcome(
            action_id=state.current_action.action_id,
            goal_id=state.current_action.goal_id,
            status="failed",
            output_contract=state.current_action.output_contract,
            observation=observation,
            error_code="executor_failed",
            retryable=False,
            provider_calls=state.provider_call_count,
        )
        _append_execution_event(state, deps, "attempt_recorded", goal_id=state.current_action.goal_id, payload={
            "attempt": AttemptRef(
                action_id=state.current_action.action_id,
                meta_capability=state.current_action.meta_capability,
                status="failed",
            ).model_dump(mode="json"),
        })
        _append_execution_event(state, deps, "goal_blocked", goal_id=state.current_action.goal_id, payload={
            "evidence_gaps": ("executor_failed",),
        })
        state.errors = []
    elif state.pending_confirmation is not None or any(status == "awaiting_confirmation" for status in statuses):
        outcome = ActionOutcome(
            action_id=state.current_action.action_id,
            goal_id=state.current_action.goal_id,
            status="awaiting_input",
            output_contract=state.current_action.output_contract,
        )
    else:
        result_keys = tuple(
            step.output_artifact_id for step in state.step_execution.steps if step.output_artifact_id
        )
        observation = ObservationRef(
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
            if additional.output_contract in {"Answer", "ProtocolOutcome"}:
                _append_execution_event(state, deps, "goal_candidate_complete", goal_id=additional.goal_id)
        if state.current_action.output_contract in {"Answer", "ProtocolOutcome"}:
            _append_execution_event(state, deps, "goal_candidate_complete", goal_id=state.current_action.goal_id)
        elif state.current_action.output_contract == "AgentArtifact":
            # Delegated artifacts require synthesis by the parent before completion.
            _append_execution_event(state, deps, "goal_activated", goal_id=state.current_action.goal_id)
        if state.current_action.payload.get("protocol_id"):
            from personal_agent.kernel.contracts.agentic import ContextItem

            receipt_items = []
            for result in state.step_execution.results.values():
                if not isinstance(result, dict) or not result.get("note_id"):
                    continue
                note_id = str(result["note_id"])
                receipt_items.append(ContextItem(
                    ref_id=note_id,
                    kind="mutation_receipt",
                    provenance=str(state.current_action.payload["protocol_id"]),
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
            state.add_event("protocol_completed", {
                "protocol_id": state.current_action.payload["protocol_id"],
                "goal_id": state.current_action.goal_id,
            })
    state.current_action_outcome = outcome
    if outcome.observation is not None:
        state.latest_observations.append(outcome.observation)
    state.add_event("action_outcome", outcome.model_dump(mode="json"))
    return {
        "current_action_outcome": state.current_action_outcome,
        "latest_observations": state.latest_observations,
        "execution_ledger": state.execution_ledger,
        "execution_events": state.execution_events,
        "context_envelope": state.context_envelope,
        "errors": state.errors,
        "events": state.events,
    }


def _node_verify_goal_progress(state: AgentGraphState, *, deps: ExecutiveContext) -> dict:
    if state.task_spec is None or state.execution_ledger is None:
        return {}
    candidates = [item for item in state.execution_ledger.items if item.status == "candidate_complete"]
    for goal in candidates:
        verification_results = [
            item for item in state.tool_results if isinstance(item, dict)
        ]
        verification_results.extend(
            item for item in state.step_execution.results.values() if isinstance(item, dict)
        )
        report = deps.goal_verifier.verify(
            state.task_spec,
            goal,
            answer=state.answer,
            citation_count=len(state.citations),
            tool_results=tuple(verification_results),
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
        state.add_event("goal_verification", report.model_dump(mode="json"))
    return {
        "execution_ledger": state.execution_ledger,
        "execution_events": state.execution_events,
        "events": state.events,
    }


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
        "completion_report": state.completion_report,
        "answer_completed": state.answer_completed,
        "latest_observations": state.latest_observations,
        "execution_ledger": state.execution_ledger,
        "execution_events": state.execution_events,
        "events": state.events,
    }


def _node_recover_action(state: AgentGraphState) -> dict:
    if state.step_execution.current_step_index >= len(state.step_execution.steps):
        state.control_route = "action_done"
        return {"control_route": state.control_route}
    step = state.step_execution.steps[state.step_execution.current_step_index]
    if step.retry_count < min(step.max_retries, 2):
        step.status = "planned"
        state.add_event("replan_attempted", {
            "step_id": step.step_id,
            "kind": "recovery_retry",
            "retry_count": step.retry_count,
        })
        state.control_route = "retry"
    else:
        state.control_route = "action_done"
        state.add_event("replan_completed", {
            "step_id": step.step_id,
            "result": "escalated_to_executive",
        })
    return {
        "step_execution": state.step_execution,
        "control_route": state.control_route,
        "events": state.events,
    }


def _after_apply_decision(state: AgentGraphState) -> str:
    return state.control_route or "loop"


def _after_recovery(state: AgentGraphState) -> str:
    return "retry" if state.control_route == "retry" else "action_done"


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
        "answer": state.answer,
        "answer_completed": state.answer_completed,
        "events": state.events,
    }


def _step_for_action(state: AgentGraphState, action: BoundedAction) -> ExecutionStep:
    intent = _semantic_label_for_goal(state, action.goal_id)
    action_type = {
        "acquire": "retrieve" if intent == "ask" else "resolve",
        "explore": "resolve",
        "reason": "compose",
        "transform": "compose",
        "verify": "verify",
        "delegate": "agent_call",
    }.get(action.meta_capability, "compose")
    execution_mode = "react" if action.meta_capability == "explore" else "deterministic"
    requirements = []
    if action.requirement is not None and action.requirement.operations and action.meta_capability not in {"acquire"}:
        requirements = [action.requirement.model_dump(mode="json")]
    return ExecutionStep(
        step_id=action.action_id,
        action_type=action_type,
        description=action.description,
        expected_output=action.output_contract,
        success_criteria="produce the declared output contract",
        on_failure="retry",
        execution_mode=execution_mode,
        max_iterations=action.max_iterations,
        workflow_id="executive_action",
        workflow_version="v1",
        projection_kind="bounded_action",
        task_id=action.goal_id,
        task_intent=intent,
        task_input=action.payload.get("task_text", action.description),
        meta_capability=action.meta_capability,
        output_contract=action.output_contract,
        capability_requirements=requirements,
        skill_ids=list(state.execution_ledger.active_skill_ids) if state.execution_ledger else [],
    )


def _materialize_delegate(
    state: AgentGraphState,
    deps: ExecutiveContext,
    decision: DelegateDecision,
) -> tuple[BoundedAction, ExecutionStep, CapabilityGapObservation | None]:
    requirement = decision.subtask.required_capability
    registry = build_capability_registry(agents=deps.agent_gateway.definitions())
    resolution = CapabilityResolver(registry, policy_engine=deps.policy_engine).resolve(
        CapabilityResolutionRequest(
            task_text=decision.subtask.goal,
            workflow_id="executive_delegate",
            step_id=decision.subtask.subtask_id,
            step_action_type="delegate",
            allowed_kinds=("agent",),
            allowed_operations=("delegate",),
            requirements=(requirement,),
            policy=CapabilitySelectionPolicy(read_only=True),
        )
    )
    if not resolution.allowed_agents or any(item.status != "satisfied" for item in resolution.coverage):
        coverage = resolution.coverage[0] if resolution.coverage else None
        gap = CapabilityGapObservation(
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
    action = BoundedAction(
        action_id=decision.subtask.subtask_id,
        goal_id=decision.target_goal_id,
        meta_capability="delegate",
        description=decision.subtask.goal,
        output_contract="AgentArtifact",
        requirement=requirement,
        max_tool_calls=decision.subtask.max_provider_calls,
        max_model_calls=0,
        payload={"task_text": decision.subtask.goal, "agent_id": agent_id},
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


def _semantic_label_for_goal(state: AgentGraphState, goal_id: str) -> str:
    if state.router_decision is not None:
        goal = next((item for item in state.router_decision.goals if item.goal_id == goal_id), None)
        if goal is not None:
            return goal.intent
    return "direct_answer"


def _action_summary(state: AgentGraphState) -> str:
    if state.answer:
        return state.answer[:1500]
    results = [
        value for value in state.step_execution.results.values()
        if value is not None
    ]
    return str(results[-1])[:1500] if results else "action completed"


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
    elif isinstance(decision, InvokeProtocolDecision):
        payload["protocol_id"] = decision.protocol_call.protocol_id
    elif isinstance(decision, DelegateDecision):
        payload["subtask_goal"] = decision.subtask.goal
    elif isinstance(decision, ActivateSkillDecision):
        payload["skill_id"] = decision.skill_id
    elif isinstance(decision, RevisePlanDecision):
        payload["patch_operations"] = [
            {"op": item.op, "goal_id": item.goal_id, "values": item.values}
            for item in decision.proposed_ledger_patch.operations
        ]
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:16]


__all__ = [
    "_after_apply_decision",
    "_after_completion",
    "_after_recovery",
    "_node_apply_decision",
    "_node_decide",
    "_node_interpret_goal",
    "_node_observe_action",
    "_node_project_control_state",
    "_node_recover_action",
    "_node_validate_decision",
    "_node_verify_completion",
    "_node_verify_goal_progress",
]
