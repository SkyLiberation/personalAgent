"""Task-level semantic proposal port; deterministic code never synthesizes business actions."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.runtime.contracts.task import (
    MaterializedGoalView,
    TaskContract,
    TaskRuntimeProjection,
    materialize_goals,
)
from personal_agent.runtime.contracts.control import (
    CapabilityClassSummary,
    BoundedAction,
    CapabilityActionInput,
    ClarifyDecision,
    CompletionClaim,
    ControlDecision,
    ControlProposal,
    ControlState,
    DecisionBasis,
    DelegateDecision,
    ExecuteBoundedActionDecision,
    FinishDecision,
    InvokeProcedureDecision,
    ModelGroundingClaim,
    ObservationRef,
    ProposedResourceAccessPlan,
    RequestCapabilityAcquisitionDecision,
    RequestConfirmationDecision,
    TerminateDecision,
    canonical_digest,
)
from personal_agent.skills import SkillRegistry

if TYPE_CHECKING:
    from personal_agent.capabilities.contracts.model import StructuredModelClient

logger = logging.getLogger(__name__)


ExecutiveAction = Literal[
    "clarify",
    "execute_bounded_action",
    "delegate",
    "invoke_procedure",
    "request_confirmation",
    "request_capability_acquisition",
    "finish",
    "terminate",
]


class _ExecutiveDecisionKindProposal(BaseModel):
    """Model-owned action/schema choice; it contains no business payload."""

    model_config = ConfigDict(extra="forbid")

    action: ExecutiveAction
    target_goal_id: str


class _ClarifyProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ClarifyDecision


class _ExecuteBoundedActionProposalBody(BaseModel):
    """Provider-portable model form for the capability-action branch.

    The public ``BoundedAction`` includes an input union used by procedure
    runtime internals. A model executive chooses procedure/delegation through
    their own decision kinds, so its atomic-action schema is intentionally a
    single capability-input shape. Conversion below is field-preserving.
    """

    model_config = ConfigDict(extra="forbid")

    decision: "_ModelExecuteBoundedActionDecision"
    grounding_claim: "_ModelExecuteGroundingClaim"


class _ModelResourceAccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_domain: str
    locator: str = ""


class _ModelExecuteGroundingClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    source_ref: str
    source_locator: str = ""
    transform: Literal["identity"] = "identity"
    origin: Literal["source_identity"] = "source_identity"
    output_field_ref: Literal["decision.target_goal_id"] = "decision.target_goal_id"
    source_digest: str


class _ModelCapabilityAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_intent: Literal[
        "acquire", "explore", "reason", "verify", "transform", "commit", "remember",
    ]
    description: str
    output_contract: str
    requirement_output_contract: str
    requirement_id: str = ""
    requirement_purpose: str = ""
    requirement_semantic_domains: tuple[str, ...] = ()
    requirement_resource_types: tuple[str, ...] = ()
    requirement_operations: tuple[str, ...] = ()
    requirement_resource_locator: str = ""
    requirement_minimum_trust: Literal["trusted", "scoped", "external", "untrusted"] = "external"
    requirement_freshness_required: bool = False
    requirement_required_providers: tuple[str, ...] = ()
    read_set: tuple[_ModelResourceAccess, ...] = ()
    write_set: tuple[_ModelResourceAccess, ...] = ()
    side_effect_class: str
    authority_scope: str
    data_egress_class: Literal["none", "metadata", "content", "sensitive"]
    trust_floor: Literal["trusted", "scoped", "external", "untrusted"]
    freshness_contract: str
    evidence_contract: str
    failure_semantics: str
    max_tool_calls: int = Field(ge=0, le=64)
    max_model_calls: int = Field(ge=0, le=16)
    max_iterations: int = Field(ge=1, le=12)
    task_text: str
    plan_step_ref: str = ""
    information_goal: str = ""
    execution_guidance: tuple[str, ...] = ()
    agentic_synthesis: bool = False


class _ModelDecisionBasis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unmet_criterion_ids: tuple[str, ...] = ()
    triggering_observation_ids: tuple[str, ...] = ()
    evidence_gap_ids: tuple[str, ...] = ()
    expected_state_change: str = ""
    rejected_action_codes: tuple[str, ...] = ()


class _ModelExecuteBoundedActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["execute_bounded_action"] = "execute_bounded_action"
    target_goal_id: str
    basis: _ModelDecisionBasis
    expected_progress: str
    bounded_action: _ModelCapabilityAction


class _DelegateProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: DelegateDecision
    grounding_claims: tuple[ModelGroundingClaim, ...] = ()


class _InvokeProcedureProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: InvokeProcedureDecision
    grounding_claims: tuple[ModelGroundingClaim, ...] = ()


class _RequestConfirmationProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: RequestConfirmationDecision


class _RequestCapabilityAcquisitionProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: RequestCapabilityAcquisitionDecision


class _FinishProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: FinishDecision


class _TerminateProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: TerminateDecision


_ACTION_PROPOSAL_TYPES: dict[ExecutiveAction, type[BaseModel]] = {
    "clarify": _ClarifyProposalBody,
    "execute_bounded_action": _ExecuteBoundedActionProposalBody,
    "delegate": _DelegateProposalBody,
    "invoke_procedure": _InvokeProcedureProposalBody,
    "request_confirmation": _RequestConfirmationProposalBody,
    "request_capability_acquisition": _RequestCapabilityAcquisitionProposalBody,
    "finish": _FinishProposalBody,
    "terminate": _TerminateProposalBody,
}


def _normalize_execute_proposal(
    body: _ExecuteBoundedActionProposalBody,
) -> _ExecutiveProposalBody:
    """Field-preserving conversion from the flat model contract to runtime types."""

    from personal_agent.capabilities.contracts.execution import CapabilityRequirement

    proposed = body.decision.bounded_action
    requirement = None
    if proposed.requirement_operations:
        requirement = CapabilityRequirement.from_dimensions(
            requirement_id=proposed.requirement_id,
            purpose=proposed.requirement_purpose,
            semantic_domains=proposed.requirement_semantic_domains,
            resource_types=proposed.requirement_resource_types,
            operations=proposed.requirement_operations,
            resource_locator=proposed.requirement_resource_locator or None,
            minimum_trust_level=proposed.requirement_minimum_trust,
            freshness_required=proposed.requirement_freshness_required,
            required_providers=proposed.requirement_required_providers,
            output_contract=proposed.requirement_output_contract,
            side_effect_class=proposed.side_effect_class,
        )
    action = BoundedAction(
        goal_id=body.decision.target_goal_id,
        execution_intent=proposed.execution_intent,
        description=proposed.description,
        output_contract=proposed.output_contract,
        requirement=requirement,
        max_tool_calls=proposed.max_tool_calls,
        max_model_calls=proposed.max_model_calls,
        max_iterations=proposed.max_iterations,
        proposed_resource_access=ProposedResourceAccessPlan(
            read_set=tuple({
                "semantic_domain": item.semantic_domain,
                "locator": item.locator or None,
            } for item in proposed.read_set),
            write_set=tuple({
                "semantic_domain": item.semantic_domain,
                "locator": item.locator or None,
            } for item in proposed.write_set),
            side_effect_class=proposed.side_effect_class,
            authority_scope=proposed.authority_scope,
            data_egress_class=proposed.data_egress_class,
            trust_floor=proposed.trust_floor,
            freshness_contract=proposed.freshness_contract,
            evidence_contract=proposed.evidence_contract,
            failure_semantics=proposed.failure_semantics,
        ),
        input=CapabilityActionInput(
            task_text=proposed.task_text,
            plan_step_ref=proposed.plan_step_ref or None,
            information_goal=proposed.information_goal or None,
            execution_guidance=proposed.execution_guidance,
            agentic_synthesis=proposed.agentic_synthesis,
        ),
    )
    decision = ExecuteBoundedActionDecision(
        target_goal_id=body.decision.target_goal_id,
        basis=DecisionBasis(**body.decision.basis.model_dump()),
        expected_progress=body.decision.expected_progress,
        bounded_action=action,
    )
    return _ExecutiveProposalBody(
        decision=decision,
        grounding_claims=(ModelGroundingClaim(
            claim_id=body.grounding_claim.claim_id,
            source_ref=body.grounding_claim.source_ref,
            source_locator=body.grounding_claim.source_locator or None,
            transform=body.grounding_claim.transform,
            origin=body.grounding_claim.origin,
            output_field_ref=body.grounding_claim.output_field_ref,
            source_digest=body.grounding_claim.source_digest,
        ),),
    )


class _ExecutiveProposalBody(BaseModel):
    """Normalized internal result after both model-owned proposal stages."""

    model_config = ConfigDict(extra="forbid")

    decision: ControlDecision
    grounding_claims: tuple[ModelGroundingClaim, ...] = ()


class _GroundingRevisionBody(BaseModel):
    """The only model-mutable payload for a grounding-only revision."""

    model_config = ConfigDict(extra="forbid")

    grounding_claims: tuple[ModelGroundingClaim, ...] = ()


class ExecutiveController:
    """Ask the model for a complete semantic proposal or emit a typed control terminal."""

    def __init__(
        self,
        model_client: "StructuredModelClient | None" = None,
        *,
        skills: SkillRegistry | None = None,
        tenant_id: str = "default",
    ) -> None:
        self._model_client = model_client
        self.tenant_id = tenant_id
        self.skills = skills or SkillRegistry.with_builtin_trust(tenant_id)

    def propose(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        *,
        observations: tuple[ObservationRef, ...] = (),
        capability_classes: tuple[CapabilityClassSummary, ...] = (),
        control_state: ControlState | None = None,
        model_context: dict[str, object] | None = None,
        supersedes_proposal_ref: str | None = None,
        revision_feedback_ref: str | None = None,
        revision_attempt: int = 0,
        prior_decision: ControlDecision | None = None,
        revision_scope: str | None = None,
    ) -> ControlProposal:
        goals = materialize_goals(task, ledger)
        open_goals = [
            item for item in goals
            if item.status not in {"verified", "degraded", "abandoned"}
        ]
        if not open_goals:
            return self._proposal(
                task,
                ledger,
                self._finish(task, ledger),
                source="contract_derivation",
                model_context=model_context,
                supersedes_proposal_ref=supersedes_proposal_ref,
                revision_feedback_ref=revision_feedback_ref,
                revision_attempt=revision_attempt,
            )
        ready_goals = [item for item in open_goals if _dependencies_satisfied(item, ledger)]
        if not ready_goals:
            return self._proposal(
                task,
                ledger,
                TerminateDecision(
                    target_goal_id=open_goals[0].goal_id,
                    basis=DecisionBasis(expected_state_change="task_terminated"),
                    expected_progress="stop_dependency_deadlock",
                    reason_code="goal_dependency_deadlock",
                    user_message="目标依赖未满足，运行已停止。",
                ),
                source="contract_derivation",
                model_context=model_context,
                supersedes_proposal_ref=supersedes_proposal_ref,
                revision_feedback_ref=revision_feedback_ref,
                revision_attempt=revision_attempt,
            )
        gap = next(
            (item for item in reversed(observations) if item.kind == "capability_gap"),
            None,
        )
        if gap is not None and control_state is not None:
            goal = next((item for item in ready_goals if item.goal_id == gap.goal_id), ready_goals[0])
            resources = task.resources_for_goal(goal.goal_id)
            from personal_agent.capabilities.contracts.execution import CapabilityRequirement

            requirement = CapabilityRequirement.from_dimensions(
                requirement_id=getattr(gap, "requirement_id", f"{goal.goal_id}:capability-gap"),
                purpose="satisfy_declared_capability_gap",
                semantic_domains=tuple(dict.fromkeys(item.semantic_domain for item in resources)),
                resource_types=tuple(dict.fromkeys(
                    value for item in resources for value in item.resource_types
                )),
                operations=tuple(dict.fromkeys(
                    operation for item in resources for operation in item.required_operations
                )),
                output_contract=goal.output_contract,
            )
            return self._proposal(
                task,
                ledger,
                RequestCapabilityAcquisitionDecision(
                    target_goal_id=goal.goal_id,
                    basis=_basis(goal, observations),
                    expected_progress="request_missing_capability",
                    requirement=requirement,
                ),
                source="contract_derivation",
                model_context=model_context,
                supersedes_proposal_ref=supersedes_proposal_ref,
                revision_feedback_ref=revision_feedback_ref,
                revision_attempt=revision_attempt,
            )
        body = self._model_proposal(
            task,
            ready_goals,
            observations,
            capability_classes,
            control_state,
            model_context,
            prior_decision=prior_decision,
            revision_scope=revision_scope,
        )
        if body is None:
            return self._proposal(
                task,
                ledger,
                TerminateDecision(
                    target_goal_id=ready_goals[0].goal_id,
                    basis=_basis(ready_goals[0], observations),
                    expected_progress="model_unavailable_stop",
                    reason_code="executive_model_unavailable",
                    user_message="模型决策能力暂不可用，运行已安全停止。",
                ),
                source="contract_derivation",
                model_context=model_context,
                supersedes_proposal_ref=supersedes_proposal_ref,
                revision_feedback_ref=revision_feedback_ref,
                revision_attempt=revision_attempt,
            )
        return ControlProposal(
            base_task_revision=task.revision,
            base_runtime_revision=ledger.revision,
            model_invocation_ref="executive_decision",
            context_projection_ref=str((model_context or {}).get("projection_id") or "") or None,
            source="model",
            decision=body.decision,
            grounding_claims=body.grounding_claims,
            supersedes_proposal_ref=supersedes_proposal_ref,
            revision_feedback_ref=revision_feedback_ref,
            revision_attempt=revision_attempt,
        )

    def terminal_proposal(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        *,
        reason_code: str,
        user_message: str,
    ) -> ControlProposal:
        goal_id = ledger.active_goal_ids[0] if ledger.active_goal_ids else task.goal_graph.goals[0].goal_id
        return self._proposal(
            task,
            ledger,
            TerminateDecision(
                target_goal_id=goal_id,
                basis=DecisionBasis(expected_state_change="task_terminated"),
                expected_progress="control_terminal",
                reason_code=reason_code,
                user_message=user_message,
            ),
            source="contract_derivation",
            model_context=None,
        )

    def _model_proposal(
        self,
        task: TaskContract,
        ready_goals: list[MaterializedGoalView],
        observations: tuple[ObservationRef, ...],
        capability_classes: tuple[CapabilityClassSummary, ...],
        control_state: ControlState | None,
        model_context: dict[str, object] | None,
        *,
        prior_decision: ControlDecision | None,
        revision_scope: str | None,
    ) -> _ExecutiveProposalBody | None:
        if self._model_client is None or model_context is None:
            return None
        selected_action: ExecutiveAction | None = None
        try:
            from personal_agent.capabilities.contracts.model import StructuredModelRequest

            ready_ids = {item.goal_id for item in ready_goals}
            context_payload = {
                "model_context": model_context,
                "ready_goal_ids": sorted(ready_ids),
                "ready_goal_contracts": {
                    item.goal_id: {
                        "result_contract": item.result_contract,
                        "output_contract": item.output_contract,
                    }
                    for item in ready_goals
                },
                "accepted_resource_ceiling": _accepted_resource_ceiling(
                    task,
                    ready_ids,
                ),
                "observations": [item.model_dump(mode="json") for item in observations[-6:]],
                "capability_classes": [item.model_dump(mode="json") for item in capability_classes],
                "procedure_candidates": [
                    item.model_dump(mode="json")
                    for item in (control_state.procedure_candidates if control_state else ())
                ],
                "grounding_sources": _grounding_source_payload(task, control_state),
            }
            if revision_scope == "grounding_only":
                if prior_decision is None:
                    return None
                if isinstance(prior_decision, ExecuteBoundedActionDecision):
                    source_ref = f"goal:{prior_decision.target_goal_id}:goal_id"
                    source = next(
                        (item for item in context_payload["grounding_sources"]
                         if item["source_ref"] == source_ref),
                        None,
                    )
                    if source is None:
                        return None
                    grounding_messages = [
                        {
                            "role": "system",
                            "content": (
                                "Revise exactly one immutable target-binding grounding claim. "
                                "Return the supplied source_ref, source_digest and source_locator unchanged. "
                                "The output field is fixed by the schema. Return only the structured object."
                            ),
                        },
                        {"role": "user", "content": json.dumps({
                            "required_source": source,
                            "immutable_decision": prior_decision.model_dump(mode="json"),
                        }, ensure_ascii=False)},
                    ]
                    grounding_response = self._model_client.generate(StructuredModelRequest(
                        operation="executive_execute_grounding_revision",
                        version="v3",
                        messages=grounding_messages,
                        output_type=_ModelExecuteGroundingClaim,
                        context_projection_ref=str(model_context.get("projection_id") or ""),
                        temperature=0,
                        max_tokens=280,
                        kind="structured",
                        metadata={"task_id": task.task_id, "revision_scope": revision_scope},
                    ))
                    claim = grounding_response.value
                    return _ExecutiveProposalBody(
                        decision=prior_decision,
                        grounding_claims=(ModelGroundingClaim(
                            claim_id=claim.claim_id,
                            source_ref=claim.source_ref,
                            source_locator=claim.source_locator or None,
                            transform=claim.transform,
                            origin=claim.origin,
                            output_field_ref=claim.output_field_ref,
                            source_digest=claim.source_digest,
                        ),),
                    )
                grounding_messages = [
                    {
                        "role": "system",
                        "content": (
                            "Revise only the grounding claims for the immutable prior decision. "
                            "Do not restate or change the decision. Use only supplied grounding_sources. "
                            "Identity claims require exact value equality; omit unsupported optional claims. "
                            "Return only the structured object."
                        ),
                    },
                    {"role": "user", "content": json.dumps({
                        "immutable_decision": prior_decision.model_dump(mode="json"),
                        **context_payload,
                    }, ensure_ascii=False)},
                ]
                grounding_response = self._model_client.generate(StructuredModelRequest(
                    operation="executive_grounding_revision",
                    version="v3",
                    messages=grounding_messages,
                    output_type=_GroundingRevisionBody,
                    context_projection_ref=str(model_context.get("projection_id") or ""),
                    temperature=0,
                    max_tokens=900,
                    kind="structured",
                    metadata={"task_id": task.task_id, "revision_scope": revision_scope},
                ))
                return _ExecutiveProposalBody(
                    decision=prior_decision,
                    grounding_claims=grounding_response.value.grounding_claims,
                )
            selection_messages = [
                {
                    "role": "system",
                    "content": (
                        "Choose exactly one executive action and one ready target goal. You own this "
                        "semantic choice. Do not produce the action payload yet. Do not claim execution "
                        "success or completion without verified reports. A finish decision only closes work "
                        "already verified in model_context; it never creates an answer. For a self-contained "
                        "response that still needs to be produced, select execute_bounded_action. If the selected "
                        "Goal has a mandatory procedure candidate, select execute_bounded_action rather than "
                        "invoke_procedure: your complete commit Proposal is later compiled into that unique "
                        "procedure by policy, and the procedure never creates the business intent. Do not select "
                        "request_confirmation for that Goal: the mandatory procedure owns the confirmation pause "
                        "after the complete mutation has been accepted and resolved to its immutable Command. "
                        "For a Goal without a mandatory procedure and with a non-empty accepted resource ceiling, "
                        "select execute_bounded_action only when at least one supplied capability_classes entry "
                        "covers its domain, resource types, operations, freshness floor, trust floor, and every "
                        "explicitly required provider. If no complete available class exists, select "
                        "request_capability_acquisition for that non-procedure Goal; do not weaken or remove the "
                        "accepted provider constraint. This capability-class precondition does not apply to a "
                        "mandatory procedure Goal: its workflow-only leaf capabilities are resolved and admitted "
                        "inside the procedure after the complete business mutation is frozen. For that Goal, do "
                        "not select request_capability_acquisition at this boundary. Capability acquisition is a "
                        "control pause, not Goal progress or execution success. When the accepted resource "
                        "ceiling requires operation delegate and a supplied capability_classes entry has "
                        "kind=agent covering that operation and required provider, select delegate; never put "
                        "delegate inside execute_bounded_action. "
                        "Return only the structured object."
                    ),
                },
                {"role": "user", "content": json.dumps(context_payload, ensure_ascii=False)},
            ]
            selection_response = self._model_client.generate(StructuredModelRequest(
                operation="executive_decision_kind",
                version="v7",
                messages=selection_messages,
                output_type=_ExecutiveDecisionKindProposal,
                context_projection_ref=str(model_context.get("projection_id") or ""),
                temperature=0,
                max_tokens=240,
                kind="structured",
                metadata={"task_id": task.task_id, "ready_goal_ids": sorted(ready_ids)},
            ))
            selection = selection_response.value
            selected_action = selection.action
            if selection.target_goal_id not in ready_ids:
                return None

            proposal_type = _ACTION_PROPOSAL_TYPES[selection.action]
            goal_resources = task.resources_for_goal(selection.target_goal_id)
            relevant_capability_classes = tuple(
                item for item in capability_classes
                if not goal_resources or any(
                    resource.semantic_domain in item.semantic_domains
                    and (
                        not resource.resource_types
                        or bool(set(resource.resource_types).intersection(item.resource_types))
                    )
                    and set(resource.required_operations).issubset(item.operations)
                    for resource in goal_resources
                )
            )
            proposal_messages = [
                {
                    "role": "system",
                    "content": (
                        "Produce the complete typed executive decision for the selected action and goal. "
                        "The selected action and target are immutable. You own all remaining semantic "
                        "choices: typed business payload, "
                        "requested result contract, grounding claims, and semantic recovery intent. "
                        "For execute_bounded_action, bounded_action.output_contract MUST be an exact "
                        "byte-for-byte copy of ready_goal_contracts[selected_target_goal_id].output_contract; "
                        "never replace it with a prose description of the desired answer. "
                        "For delegate, subtask.required_capability must copy the matching kind=agent "
                        "capability class dimensions, preserve the accepted required provider, and agent_id "
                        "must name that provider. The bounded_sub_goal/task text is model-owned but must stay "
                        "within the selected Goal; the child Artifact remains unverified until parent verification. "
                        "max_tool_calls and max_model_calls may be zero, but max_iterations MUST be an "
                        "integer from 1 through 12 even for a one-shot self-contained response. "
                        "When a capability is required by a non-procedure action, requirement_output_contract, authority_scope, "
                        "side_effect_class, data_egress_class, trust_floor, freshness_contract, "
                        "evidence_contract, and failure_semantics MUST describe one supplied "
                        "capability_classes entry that covers the requested domain/resource/operations. "
                        "Copy those eight class fields exactly; do not reinterpret them. In particular, "
                        "data_egress_class describes data sent out of this process to the provider, so a "
                        "local artifact reader whose class says none remains none even though its result "
                        "contains content. capability_classes.providers describes availability only: keep "
                        "requirement_required_providers empty unless the accepted resource ceiling itself "
                        "contains an explicit required provider. "
                        "The capability's immediate output contract may be ToolResult or EvidenceItem "
                        "while bounded_action.output_contract remains the Goal's final Answer contract. "
                        "Choose procedures only from the supplied candidates; for a mandatory procedure, "
                        "provide its complete typed input rather than asking runtime to synthesize it. "
                        "Do not bind a concrete provider unless the user contract already requires it. "
                        "If accepted_resource_ceiling[selected_target_goal_id] contains non-empty "
                        "provider_constraint.required, capability requirement.provider_constraint.required "
                        "MUST preserve that exact set; omission is forbidden. Do not add any required "
                        "provider absent from that ceiling. Also preserve its freshness_required floor. "
                        "For a mandatory procedure commit, declare the accepted Goal's mutation operations and "
                        "resource boundary completely, but do not claim agentic synthesis and do not require a "
                        "top-level capability class: leaf capability binding belongs to the procedure nodes. "
                        "For execute_bounded_action, read_set and write_set MUST remain within "
                        "accepted_resource_ceiling[selected_target_goal_id]. An empty ceiling requires "
                        "both sets to be empty; consuming an admitted predecessor output is not a new "
                        "resource access. Any non-empty read_set or write_set requires a non-empty "
                        "capability requirement_operations list and max_tool_calls >= 1; it can never "
                        "use the internal self-contained reasoning path. Never invent a semantic domain "
                        "or locator. "
                        "Do not claim execution success or completion without verified reports. "
                        "When revising, obey DecisionFeedback mutable/immutable fields and revision scope. "
                        "For execute_bounded_action, provide exactly one target-binding grounding_claim: "
                        "source_ref must be goal:<selected_target_goal_id>:goal_id, use its supplied digest, "
                        "and do not create any other grounding assertions. For other actions, provide grounding "
                        "claims only where their output schema requires them. "
                        "For a Goal whose result contract is external_state, its mutation Proposal must be complete: "
                        "use execution_intent=commit, a non-none side_effect_class, a non-empty write_set, and a "
                        "non-empty requirement_operations set drawn only from that Goal's declared resource operations. "
                        "The task_text is the exact business content to be written, never the surrounding user "
                        "instruction. For example, for ‘把“事实 X”记入知识库，然后回答问题’, task_text must be ‘事实 X’, "
                        "not the full sentence containing ‘记入’、‘然后’ or the follow-up question. Do not add facts "
                        "or targets that are absent from the accepted Goal. If a mandatory procedure candidate applies, "
                        "this complete accepted commit is compiled to that procedure by policy; do not omit its mutation "
                        "fields in expectation that runtime will fill them. "
                        "For a self-contained response, choose reason or transform with max_tool_calls=0 and "
                        "an empty requirement_operations list: composing the response uses the admitted model "
                        "call, not an external capability provider. Set agentic_synthesis=false for that path; "
                        "agentic_synthesis=true is only valid when a non-empty capability requirement and at "
                        "least one tool call are necessary for the selected semantic result. "
                        "When agentic_synthesis=true with a capability requirement, max_iterations and "
                        "max_model_calls must both be at least 2: the first turn must call an allowed tool, "
                        "and finish_react is valid only after the governed Observation has been consumed. "
                        "Return only the structured object and never reveal chain-of-thought."
                    ),
                },
                {"role": "user", "content": json.dumps({
                    "selected_action": selection.action,
                    "selected_target_goal_id": selection.target_goal_id,
                    "revision_scope": revision_scope,
                    "rejected_prior_decision": (
                        prior_decision.model_dump(mode="json")
                        if prior_decision is not None else None
                    ),
                    **context_payload,
                    "capability_classes": [
                        item.model_dump(mode="json")
                        for item in relevant_capability_classes
                    ],
                }, ensure_ascii=False)},
            ]
            response = self._model_client.generate(StructuredModelRequest(
                operation=f"executive_{selection.action}_proposal",
                version="v10",
                messages=proposal_messages,
                output_type=proposal_type,
                context_projection_ref=str(model_context.get("projection_id") or ""),
                temperature=0,
                max_tokens=1800,
                kind="structured",
                metadata={"task_id": task.task_id, "ready_goal_ids": sorted(ready_ids)},
            ))
            body = (
                _normalize_execute_proposal(response.value)
                if isinstance(response.value, _ExecuteBoundedActionProposalBody)
                else _ExecutiveProposalBody(
                    decision=response.value.decision,
                    grounding_claims=getattr(response.value, "grounding_claims", ()),
                )
            )
            decision = body.decision
            if (
                decision.action != selection.action
                or decision.target_goal_id != selection.target_goal_id
            ):
                return None
            return body
        except Exception:
            logger.exception("Executive proposal generation failed action=%s", selected_action)
            return None


    @staticmethod
    def _proposal(
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        decision: ControlDecision,
        *,
        source: str,
        model_context: dict[str, object] | None,
        supersedes_proposal_ref: str | None = None,
        revision_feedback_ref: str | None = None,
        revision_attempt: int = 0,
    ) -> ControlProposal:
        return ControlProposal(
            base_task_revision=task.revision,
            base_runtime_revision=ledger.revision,
            context_projection_ref=str((model_context or {}).get("projection_id") or "") or None,
            source=source,
            decision=decision,
            supersedes_proposal_ref=supersedes_proposal_ref,
            revision_feedback_ref=revision_feedback_ref,
            revision_attempt=revision_attempt,
        )

    @staticmethod
    def _finish(task: TaskContract, ledger: TaskRuntimeProjection) -> FinishDecision:
        goals = materialize_goals(task, ledger)
        return FinishDecision(
            target_goal_id=goals[-1].goal_id,
            basis=DecisionBasis(expected_state_change="task_completed"),
            expected_progress="verified_completion",
            completion_claim=CompletionClaim(
                goal_ids=tuple(item.goal_id for item in goals),
                criterion_ids=tuple(item.criterion_id for item in task.success_criteria),
            ),
        )


def _accepted_resource_ceiling(
    task: TaskContract,
    goal_ids: set[str],
) -> dict[str, list[dict[str, object]]]:
    """Serialize the immutable TaskContract resource ceiling for model proposals."""
    return {
        goal_id: [
            resource.model_dump(mode="json")
            for resource in task.resources_for_goal(goal_id)
        ]
        for goal_id in sorted(goal_ids)
    }


def _dependencies_satisfied(goal: MaterializedGoalView, ledger: TaskRuntimeProjection) -> bool:
    return all(
        ledger.goal_states.get(dependency.dependency_goal_id) is not None
        and ledger.goal_states[dependency.dependency_goal_id].status in {"verified", "degraded"}
        for dependency in goal.dependencies
        if dependency.blocks_execution
    )


def _basis(
    goal: MaterializedGoalView,
    observations: tuple[ObservationRef, ...],
) -> DecisionBasis:
    scoped = tuple(item for item in observations if not item.goal_id or item.goal_id == goal.goal_id)
    return DecisionBasis(
        unmet_criterion_ids=goal.success_criterion_ids,
        triggering_observation_ids=tuple(item.observation_id for item in scoped[-3:]),
        evidence_gap_ids=goal.evidence_gaps,
        expected_state_change="advance_goal",
    )


def _grounding_source_payload(
    task: TaskContract,
    control_state: ControlState | None,
) -> list[dict[str, object]]:
    values: dict[str, object] = {f"task:{task.task_id}:user_goal": task.user_goal}
    for goal in task.goal_graph.goals:
        values[f"goal:{goal.goal_id}:goal_id"] = goal.goal_id
        values[f"goal:{goal.goal_id}:description"] = goal.description
        for criterion in goal.criteria:
            values[f"criterion:{criterion.criterion_id}:criterion_id"] = criterion.criterion_id
            values[f"criterion:{criterion.criterion_id}:description"] = criterion.description
        for constraint in goal.constraints:
            values[f"constraint:{constraint.constraint_id}"] = constraint.description
    if control_state is not None:
        for observation in control_state.latest_observations:
            values[f"observation:{observation.observation_id}"] = observation.summary
    return [
        {
            "source_ref": source_ref,
            "value": value,
            "source_digest": canonical_digest(value),
        }
        for source_ref, value in values.items()
    ]


__all__ = ["ExecutiveController"]
