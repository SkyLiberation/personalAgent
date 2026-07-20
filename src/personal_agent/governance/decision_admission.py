"""Admission, semantic freezing, and deterministic execution-command resolution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

from personal_agent.capabilities.contracts.procedure import (
    ConversationSolidifyInput,
    KnowledgeConsolidateInput,
    KnowledgeDeleteInput,
    KnowledgeIngestInput,
    ResearchRunInput,
    ProcedureCandidate,
    ProcedureInvocation,
    ProcedureRef,
)
from personal_agent.governance.contracts.admission import (
    AdmissionDisposition,
    DecisionFeedback,
    GovernanceSnapshotRef,
    StageAdmissionDecision,
)
from personal_agent.kernel.contracts.resource import MUTATING_OPERATIONS
from personal_agent.runtime.contracts.control import (
    AcceptedIntent,
    AuthorizationProjection,
    CapabilityActionInput,
    ClarifyDecision,
    ControlProposal,
    ControlState,
    ControlDecision,
    DelegateDecision,
    DerivationInvariantResults,
    DerivationRecord,
    ExecuteBoundedActionDecision,
    FinishDecision,
    InvokeProcedureDecision,
    RequestCapabilityAcquisitionDecision,
    RequestConfirmationDecision,
    ResolvedExecutionCommand,
    ResourceAccess,
    TerminateDecision,
    canonical_digest,
)
from personal_agent.runtime.contracts.task import (
    TaskContract,
    TaskRuntimeProjection,
    materialize_goals,
)


class _DecisionDenied(ValueError):
    pass


class DispositionPolicy:
    """Map a typed denial and current environment to its only control consequence."""

    _MODEL_REVISABLE = frozenset({
        "mandatory_procedure_bypass", "action_goal_mismatch", "mutation_authority_incomplete",
        "procedure_goal_mismatch", "procedure_not_eligible", "terminal_goal_targeted",
        "procedure_parameters_incomplete", "procedure_input_kind_mismatch",
        "remaining_provider_budget_exceeded", "task_provider_budget_exceeded",
    })
    _EXTERNAL_INPUT = frozenset({"unknown_goal", "goal_dependencies_unmet", "ambiguous_resolution"})
    _ACQUISITION = frozenset({"capability_unavailable", "credential_missing", "plugin_not_installed"})
    _ENVIRONMENT_WAIT = frozenset({"provider_temporarily_unavailable", "model_temporarily_unavailable"})
    _GROUNDING_REVISABLE = frozenset({
        "grounding_required", "grounding_source_unknown",
        "grounding_source_digest_mismatch", "grounding_output_field_unknown",
        "grounding_identity_mismatch",
    })

    def evaluate(
        self,
        reason_code: str,
        *,
        acquisition_available: bool = False,
        environment_retryable: bool = False,
    ) -> tuple[AdmissionDisposition, str, tuple[str, ...], tuple[str, ...]]:
        if reason_code in self._GROUNDING_REVISABLE:
            return (
                "revise_model",
                "grounding_only",
                ("grounding_claims",),
                ("decision", "base_task_revision", "base_runtime_revision"),
            )
        if reason_code in self._MODEL_REVISABLE:
            return (
                "revise_model",
                "semantic_revision",
                ("decision", "grounding_claims"),
                ("base_task_revision", "base_runtime_revision"),
            )
        if reason_code in self._EXTERNAL_INPUT:
            return "request_external_input", "upstream_replan", (), ("decision",)
        if reason_code in self._ACQUISITION and acquisition_available:
            return "request_capability_acquisition", "parameter_completion", (), ("decision",)
        if reason_code in self._ENVIRONMENT_WAIT or environment_retryable:
            return "await_environment_change", "parameter_completion", (), ("decision",)
        return "terminal", "semantic_revision", (), ("decision",)


class DecisionValidator:
    def __init__(self, disposition_policy: DispositionPolicy | None = None) -> None:
        self._disposition_policy = disposition_policy or DispositionPolicy()

    def admit(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        proposal: ControlProposal,
        control_state: ControlState | None = None,
        *,
        prior_proposal: ControlProposal | None = None,
        revision_feedback: DecisionFeedback | None = None,
    ) -> StageAdmissionDecision:
        snapshot = GovernanceSnapshotRef(
            task_revision=task.revision,
            runtime_revision=ledger.revision,
            policy_revision="decision-admission:v3",
        )
        stale = (
            proposal.base_task_revision != task.revision
            or proposal.base_runtime_revision != ledger.revision
        )
        try:
            if stale:
                raise _DecisionDenied("stale_proposal_revision")
            self._validate_revision(proposal, prior_proposal, revision_feedback)
            self._validate_grounding(task, proposal, control_state)
            self._validate(task, ledger, proposal.decision, control_state)
        except _DecisionDenied as exc:
            reason = str(exc)
            disposition, revision_scope, mutable, immutable = self._disposition_policy.evaluate(
                reason,
                acquisition_available=reason in {"capability_unavailable", "credential_missing"},
            )
            constraint_refs = (
                f"task:{task.task_id}:revision:{task.revision}",
                f"goal:{proposal.decision.target_goal_id}",
            )
            equivalence_hash = canonical_digest({
                "stage": "control",
                "reason": reason,
                "snapshot": snapshot.model_dump(mode="json"),
                "decision": proposal.decision.model_dump(mode="json"),
            })
            feedback = DecisionFeedback(
                stage="control",
                rejected_proposal_ref=proposal.proposal_id,
                reason_codes=(reason,),
                violated_constraint_refs=constraint_refs,
                rejected_field_refs=("decision",),
                mutable_field_refs=mutable,
                immutable_field_refs=immutable,
                required_repairs=(reason,),
                revision_scope=revision_scope,
                disposition=disposition,
                revision_budget_remaining=max(task.constraints.revision_budget - proposal.revision_attempt, 0),
                governance_snapshot_ref=canonical_digest(snapshot),
                rejection_equivalence_hash=equivalence_hash,
            )
            return StageAdmissionDecision(
                proposal_ref=proposal.proposal_id,
                verdict="not_accepted",
                disposition=disposition,
                effective_constraint_refs=constraint_refs,
                reason_codes=(reason,),
                snapshot=snapshot,
                feedback=feedback,
            )
        return StageAdmissionDecision(
            proposal_ref=proposal.proposal_id,
            verdict="accepted",
            effective_constraint_refs=(
                f"task:{task.task_id}:revision:{task.revision}",
                f"goal:{proposal.decision.target_goal_id}",
            ),
            reason_codes=("decision_within_task_authority",),
            snapshot=snapshot,
        )

    @staticmethod
    def _validate_revision(
        proposal: ControlProposal,
        prior: ControlProposal | None,
        feedback: DecisionFeedback | None,
    ) -> None:
        if proposal.revision_attempt == 0:
            if proposal.supersedes_proposal_ref or proposal.revision_feedback_ref:
                raise _DecisionDenied("revision_lineage_mismatch")
            return
        if (
            prior is None
            or feedback is None
            or proposal.supersedes_proposal_ref != prior.proposal_id
            or proposal.revision_feedback_ref != feedback.feedback_id
            or feedback.rejected_proposal_ref != prior.proposal_id
        ):
            raise _DecisionDenied("revision_lineage_mismatch")
        if feedback.revision_scope == "grounding_only" and proposal.decision != prior.decision:
            raise _DecisionDenied("revision_scope_violation")
        if feedback.revision_scope == "format_only" and (
            proposal.decision != prior.decision
            or proposal.grounding_claims != prior.grounding_claims
        ):
            raise _DecisionDenied("revision_scope_violation")

    @staticmethod
    def _validate_grounding(
        task: TaskContract,
        proposal: ControlProposal,
        control_state: ControlState | None,
    ) -> None:
        if proposal.source != "model":
            return
        decision = proposal.decision
        grounding_required = isinstance(
            decision,
            (ExecuteBoundedActionDecision, InvokeProcedureDecision, DelegateDecision),
        )
        if grounding_required and not proposal.grounding_claims:
            raise _DecisionDenied("grounding_required")
        sources = _grounding_sources(task, control_state)
        decision_payload = decision.model_dump(mode="json")
        for claim in proposal.grounding_claims:
            source_value = sources.get(claim.source_ref)
            if source_value is None:
                raise _DecisionDenied("grounding_source_unknown")
            if claim.source_digest != canonical_digest(source_value):
                raise _DecisionDenied("grounding_source_digest_mismatch")
            output_path = claim.output_field_ref.removeprefix("decision.")
            output_value = _value_at_path(decision_payload, output_path)
            if output_value is None:
                raise _DecisionDenied("grounding_output_field_unknown")
            if claim.transform == "identity" and output_value != source_value:
                raise _DecisionDenied("grounding_identity_mismatch")

    def _validate(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        decision: ControlDecision,
        control_state: ControlState | None,
    ) -> None:
        goals = {item.goal_id: item for item in materialize_goals(task, ledger)}
        if decision.target_goal_id not in goals and decision.action not in {"finish", "terminate"}:
            raise _DecisionDenied("unknown_goal")
        goal = goals.get(decision.target_goal_id)
        goal_procedures = tuple(
            candidate for candidate in (control_state.procedure_candidates if control_state else ())
            if candidate.goal_id == decision.target_goal_id and candidate.status in {"eligible", "mandatory"}
        )
        mandatory = tuple(item for item in goal_procedures if item.status == "mandatory")
        if len(mandatory) > 1 and not isinstance(decision, InvokeProcedureDecision):
            raise _DecisionDenied("ambiguous_resolution")
        if (
            any(candidate.status == "mandatory" for candidate in goal_procedures)
            and not isinstance(decision, InvokeProcedureDecision)
            and not (
                isinstance(decision, ExecuteBoundedActionDecision)
                and decision.bounded_action.execution_intent == "commit"
            )
            and decision.action not in {"terminate", "clarify", "request_confirmation"}
        ):
            raise _DecisionDenied("mandatory_procedure_bypass")
        if goal is not None and decision.action not in {"finish", "terminate"}:
            unmet = tuple(
                dependency.dependency_goal_id
                for dependency in goal.dependencies
                if dependency.blocks_execution and (
                    dependency.dependency_goal_id not in goals
                    or goals[dependency.dependency_goal_id].status not in {"verified", "degraded"}
                )
            )
            if unmet:
                raise _DecisionDenied("goal_dependencies_unmet")
        if goal is not None and goal.status in {"verified", "degraded", "abandoned"} and decision.action not in {
            "finish", "terminate",
        }:
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
                or not set(action.requirement.operations).intersection(MUTATING_OPERATIONS)
            ):
                raise _DecisionDenied("mutation_authority_incomplete")
            if action.max_tool_calls > task.constraints.max_provider_calls:
                raise _DecisionDenied("task_provider_budget_exceeded")
            if control_state is not None and action.max_tool_calls > control_state.remaining_provider_calls:
                raise _DecisionDenied("remaining_provider_budget_exceeded")
            if mandatory and action.execution_intent == "commit":
                if not isinstance(action.input, CapabilityActionInput):
                    raise _DecisionDenied("procedure_parameters_incomplete")
                if mandatory[0].procedure_id == "knowledge_delete":
                    targets = tuple(
                        item.locator for item in action.proposed_resource_access.write_set
                        if item.locator
                    )
                    if len(set(targets)) != 1:
                        raise _DecisionDenied("ambiguous_resolution")
                if mandatory[0].procedure_id == "research_subscription_create":
                    raise _DecisionDenied("procedure_parameters_incomplete")
        if isinstance(decision, InvokeProcedureDecision):
            invocation = decision.procedure_invocation
            if goal is None or invocation.goal_id != goal.goal_id:
                raise _DecisionDenied("procedure_goal_mismatch")
            candidate = next((
                item for item in goal_procedures
                if item.procedure_id == invocation.procedure.procedure_id
                and item.version == invocation.procedure.version
            ), None)
            if candidate is None:
                raise _DecisionDenied("procedure_not_eligible")
            if invocation.input.kind != invocation.procedure.procedure_id:
                raise _DecisionDenied("procedure_input_kind_mismatch")
            if control_state is not None and control_state.remaining_provider_calls < 1:
                raise _DecisionDenied("procedure_provider_budget_exhausted")
        if isinstance(decision, RequestCapabilityAcquisitionDecision):
            allowed = {
                operation
                for resource in task.resources_for_goal(decision.target_goal_id)
                for operation in resource.required_operations
            }
            if allowed and not set(decision.requirement.operations).issubset(allowed):
                raise _DecisionDenied("capability_acquisition_expands_operations")
        if isinstance(decision, DelegateDecision) and control_state is not None:
            if decision.subtask.max_provider_calls > control_state.remaining_provider_calls:
                raise _DecisionDenied("delegation_provider_budget_exceeded")


class AcceptedIntentCompiler:
    def compile(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        proposal: ControlProposal,
        admission: StageAdmissionDecision,
    ) -> AcceptedIntent:
        if admission.proposal_ref != proposal.proposal_id:
            raise ValueError("admission does not reference this proposal")
        if admission.verdict != "accepted":
            raise ValueError("only accepted proposals compile to intents")
        proof = admission.monotonicity
        if any((proof.operations_expanded, proof.resources_expanded, proof.budgets_expanded, proof.semantics_modified)):
            raise ValueError("admission permits semantic or authority expansion")
        semantic_digest = proposal.intent_semantic_hash
        return AcceptedIntent(
            proposal_ref=proposal.proposal_id,
            admission_ref=admission.admission_id,
            task_id=task.task_id,
            goal_id=proposal.decision.target_goal_id,
            task_revision=task.revision,
            runtime_revision=ledger.revision,
            decision=proposal.decision,
            grounding_claims=proposal.grounding_claims,
            semantic_digest=semantic_digest,
        )


class ExecutionCommandResolver:
    """Resolve one accepted semantic intent into an immutable execution contract."""

    def resolve(
        self,
        task: TaskContract,
        intent: AcceptedIntent,
        *,
        mandatory_procedure: ProcedureCandidate | None = None,
        supersedes_command_ref: str | None = None,
        provider_binding_refs: tuple[str, ...] = (),
        provider_binding_derivations: tuple[DerivationRecord, ...] = (),
    ) -> ResolvedExecutionCommand:
        decision = intent.decision
        derived_invocation = _compile_mandatory_invocation(
            task, intent, mandatory_procedure,
        )
        route = "procedure" if derived_invocation is not None else _route_for(decision)
        procedure_id = None
        procedure_version = None
        read_set: tuple[ResourceAccess, ...] = ()
        write_set: tuple[ResourceAccess, ...] = ()
        provider_bindings = provider_binding_refs
        if provider_bindings:
            if len(provider_binding_derivations) != len(provider_bindings):
                raise ValueError("every provider binding requires one derivation record")
            derived_bindings = {item.output_ref for item in provider_binding_derivations}
            if derived_bindings != set(provider_bindings):
                raise ValueError("provider derivations do not match command bindings")
            if any(
                item.derivation_kind != "provider_binding"
                or item.invariant_results.provider_equivalence != "passed"
                for item in provider_binding_derivations
            ):
                raise ValueError("provider binding derivation does not prove equivalence")
        elif provider_binding_derivations:
            raise ValueError("provider derivations require provider bindings")
        if isinstance(decision, InvokeProcedureDecision):
            procedure_id = decision.procedure_invocation.procedure.procedure_id
            procedure_version = decision.procedure_invocation.procedure.version
            derived_invocation = decision.procedure_invocation
        elif derived_invocation is not None:
            procedure_id = derived_invocation.procedure.procedure_id
            procedure_version = derived_invocation.procedure.version
        elif isinstance(decision, ExecuteBoundedActionDecision):
            read_set = decision.bounded_action.proposed_resource_access.read_set
            write_set = decision.bounded_action.proposed_resource_access.write_set
        targets = _target_refs(task, decision)
        authorization = _authorization_projection(task, decision, targets)
        authorization_digest = canonical_digest(authorization)
        command_id = canonical_digest({
            "intent": intent.accepted_intent_id,
            "route": route,
            "supersedes": supersedes_command_ref,
            "task_revision": task.revision,
            "runtime_revision": intent.runtime_revision,
        })[:12]
        command_core = {
            "command_id": command_id,
            "accepted_intent_ref": intent.accepted_intent_id,
            "route": route,
            "procedure_id": procedure_id,
            "procedure_version": procedure_version,
            "procedure_invocation": (
                derived_invocation.model_dump(mode="json") if derived_invocation else None
            ),
            "targets": targets,
            "providers": provider_bindings,
            "provider_derivations": [
                item.model_dump(mode="json") for item in provider_binding_derivations
            ],
            "read_set": [item.model_dump(mode="json") for item in read_set],
            "write_set": [item.model_dump(mode="json") for item in write_set],
            "authorization_digest": authorization_digest,
        }
        execution_digest = canonical_digest(command_core)
        route_unique = derived_invocation is not None
        derivation = DerivationRecord(
            derivation_kind="command_resolution",
            source_contract_refs=(intent.accepted_intent_id, task.task_id),
            rule_id="accepted-intent-command-resolution",
            rule_version="v1",
            policy_snapshot_ref="execution-resolution:v1",
            input_fact_refs=(f"task-revision:{task.revision}",),
            source_digests=(intent.semantic_digest, canonical_digest(task)),
            output_ref=command_id,
            output_digest=execution_digest,
            invariant_results=DerivationInvariantResults(
                canonical_target_mapping="passed" if targets else "not_applicable",
                scope_subset="passed",
                route_uniqueness="passed" if route_unique else "not_applicable",
                provider_equivalence="passed" if provider_bindings else "not_applicable",
                authorization_projection_preserved="passed",
            ),
            uniqueness_kind="single_policy_allowed_route" if route_unique else "not_applicable",
        )
        return ResolvedExecutionCommand(
            command_id=command_id,
            accepted_intent_ref=intent.accepted_intent_id,
            supersedes_command_ref=supersedes_command_ref,
            route=route,
            procedure_id=procedure_id,
            procedure_version=procedure_version,
            procedure_invocation=derived_invocation,
            canonical_target_refs=targets,
            narrowed_scope_refs=targets,
            provider_binding_refs=provider_bindings,
            provider_binding_derivations=provider_binding_derivations,
            read_set=read_set,
            write_set=write_set,
            authorization_projection=authorization,
            authorization_digest=authorization_digest,
            execution_command_digest=execution_digest,
            derivation_record=derivation,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )


def _route_for(decision: ControlDecision) -> str:
    if isinstance(decision, InvokeProcedureDecision):
        return "procedure"
    if isinstance(decision, DelegateDecision):
        return "delegated"
    if isinstance(decision, ExecuteBoundedActionDecision):
        action = decision.bounded_action
        if (
            action.requirement is None
            and action.execution_intent in {"reason", "transform", "verify"}
            and action.proposed_resource_access.side_effect_class == "none"
        ):
            return "internal_reasoning"
        return "atomic"
    return "internal_reasoning"


def _compile_mandatory_invocation(
    task: TaskContract,
    intent: AcceptedIntent,
    candidate: ProcedureCandidate | None,
) -> ProcedureInvocation | None:
    decision = intent.decision
    if isinstance(decision, InvokeProcedureDecision):
        return decision.procedure_invocation
    if candidate is None or not isinstance(decision, ExecuteBoundedActionDecision):
        return None
    action = decision.bounded_action
    if action.execution_intent != "commit" or not isinstance(action.input, CapabilityActionInput):
        return None
    resources = task.resources_for_goal(intent.goal_id)
    resource_types = tuple(dict.fromkeys(
        value for item in resources for value in item.resource_types
    ))
    operations = tuple(dict.fromkeys(
        operation for item in resources for operation in item.required_operations
    ))
    locators = tuple(dict.fromkeys(
        item.locator for item in resources if item.locator
    ))
    procedure_input = None
    if candidate.procedure_id == "knowledge_ingest":
        procedure_input = KnowledgeIngestInput(
            text=action.input.task_text,
            resource_types=resource_types or ("text",),
            operations=operations or ("ingest",),
            locator=locators[0] if len(locators) == 1 else None,
            provenance_refs=tuple(item.claim_id for item in intent.grounding_claims),
            requested_result_contract=action.output_contract,
        )
    elif candidate.procedure_id == "knowledge_delete":
        targets = tuple(dict.fromkeys(
            item.locator for item in action.proposed_resource_access.write_set if item.locator
        )) or locators
        if len(targets) != 1:
            raise ValueError("ambiguous_resolution")
        procedure_input = KnowledgeDeleteInput(
            target_ref=targets[0],
            selection_evidence_refs=tuple(item.claim_id for item in intent.grounding_claims),
            requested_result_contract=action.output_contract,
        )
    elif candidate.procedure_id == "conversation_solidify" and len(locators) == 1:
        procedure_input = ConversationSolidifyInput(
            conversation_scope_ref=locators[0],
            requested_result_contract=action.output_contract,
        )
    elif candidate.procedure_id == "knowledge_consolidate" and locators:
        procedure_input = KnowledgeConsolidateInput(
            target_refs=locators,
            requested_result_contract=action.output_contract,
        )
    elif candidate.procedure_id == "research_subscription_create":
        raise ValueError("procedure_parameters_incomplete")
    if procedure_input is None:
        return None
    return ProcedureInvocation(
        procedure=ProcedureRef(
            procedure_id=candidate.procedure_id,
            version=candidate.version,
        ),
        goal_id=intent.goal_id,
        input=procedure_input,
        idempotency_key=(
            task.mutation_intent.idempotency_key
            if task.mutation_intent and task.mutation_intent.idempotency_key
            else f"{task.task_id}:{intent.goal_id}:{candidate.procedure_id}"
        ),
        expected_output_contract=procedure_input.requested_result_contract,
    )


def _target_refs(task: TaskContract, decision: ControlDecision) -> tuple[str, ...]:
    if isinstance(decision, InvokeProcedureDecision):
        value = decision.procedure_invocation.input
        if isinstance(value, KnowledgeDeleteInput):
            return (value.target_ref,)
        if isinstance(value, KnowledgeConsolidateInput):
            return value.target_refs
        if isinstance(value, KnowledgeIngestInput) and value.locator:
            return (value.locator,)
        if isinstance(value, ResearchRunInput) and value.locator:
            return (value.locator,)
    if isinstance(decision, ExecuteBoundedActionDecision):
        accesses = (
            *decision.bounded_action.proposed_resource_access.read_set,
            *decision.bounded_action.proposed_resource_access.write_set,
        )
        return tuple(dict.fromkeys(
            item.locator or f"domain:{item.semantic_domain}" for item in accesses
        ))
    return tuple(
        item.locator or f"{item.semantic_domain}:{index}"
        for index, item in enumerate(task.resources_for_goal(decision.target_goal_id))
    )


def _authorization_projection(
    task: TaskContract,
    decision: ControlDecision,
    targets: tuple[str, ...],
) -> AuthorizationProjection:
    operation = decision.action
    requested_result = "ControlResult"
    side_effect = "none"
    data_egress = "none"
    trust_boundary = "local"
    confirmation_risk = "none"
    provider_identity = None
    user_visible_payload = ""
    if isinstance(decision, InvokeProcedureDecision):
        value = decision.procedure_invocation.input
        requested_result = value.requested_result_contract
        operation = value.kind
        side_effect = "mutation" if task.mutation_intent is not None else "procedure"
        user_visible_payload = json.dumps(
            value.model_dump(mode="json"), ensure_ascii=False, sort_keys=True,
        )
        confirmation_risk = "mutation" if task.mutation_intent is not None else "procedure"
    elif isinstance(decision, ExecuteBoundedActionDecision):
        action = decision.bounded_action
        access = action.proposed_resource_access
        operation = action.execution_intent
        requested_result = action.output_contract
        side_effect = access.side_effect_class
        data_egress = access.data_egress_class
        trust_boundary = access.trust_floor
        user_visible_payload = json.dumps(
            action.input.model_dump(mode="json"), ensure_ascii=False, sort_keys=True,
        )
        confirmation_risk = (
            f"tool_calls<={action.max_tool_calls};model_calls<={action.max_model_calls}"
        )
        required_providers = action.requirement.required_providers if action.requirement else ()
        provider_identity = required_providers[0] if len(required_providers) == 1 else None
    elif isinstance(decision, DelegateDecision):
        requested_result = decision.subtask.expected_artifact_contract
        operation = "delegate"
        user_visible_payload = decision.subtask.goal
        data_egress = "content"
        trust_boundary = decision.subtask.required_capability.minimum_trust_level
        confirmation_risk = (
            f"tokens<={decision.subtask.token_budget};cost<={decision.subtask.cost_budget};"
            f"seconds<={decision.subtask.time_budget_seconds}"
        )
    elif isinstance(decision, FinishDecision):
        requested_result = "CompletionReport"
    elif isinstance(decision, (ClarifyDecision, RequestConfirmationDecision)):
        requested_result = "InteractionDecision"
    elif isinstance(decision, RequestCapabilityAcquisitionDecision):
        requested_result = "CapabilityAcquisitionOutcome"
    elif isinstance(decision, TerminateDecision):
        requested_result = "TerminalStatus"
    return AuthorizationProjection(
        operation=operation,
        canonical_target_set=targets,
        user_visible_payload=user_visible_payload,
        requested_result_contract=requested_result,
        side_effect_envelope=side_effect,
        data_egress_boundary=data_egress,
        trust_boundary=trust_boundary,
        confirmation_relevant_cost_and_risk=confirmation_risk,
        policy_required_provider_identity=provider_identity,
    )


def _grounding_sources(
    task: TaskContract,
    control_state: ControlState | None,
) -> dict[str, object]:
    sources: dict[str, object] = {
        f"task:{task.task_id}:user_goal": task.user_goal,
    }
    for goal in task.goal_graph.goals:
        sources[f"goal:{goal.goal_id}:goal_id"] = goal.goal_id
        sources[f"goal:{goal.goal_id}:description"] = goal.description
        for criterion in goal.criteria:
            sources[f"criterion:{criterion.criterion_id}:criterion_id"] = criterion.criterion_id
            sources[f"criterion:{criterion.criterion_id}:description"] = criterion.description
        for constraint in goal.constraints:
            sources[f"constraint:{constraint.constraint_id}"] = constraint.description
    if control_state is not None:
        for observation in control_state.latest_observations:
            sources[f"observation:{observation.observation_id}"] = observation.summary
    return sources


def _value_at_path(payload: object, field_ref: str) -> object | None:
    parts = tuple(part for part in field_ref.split(".") if part)
    if parts and parts[0] == "decision":
        parts = parts[1:]
    value = payload
    for part in parts:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


__all__ = [
    "AcceptedIntentCompiler", "DecisionValidator", "DispositionPolicy",
    "ExecutionCommandResolver",
]
