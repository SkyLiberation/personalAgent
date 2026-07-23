from __future__ import annotations

import pytest
from uuid import uuid4

from personal_agent.capabilities.contracts.execution import (
    Capability,
    CapabilityEquivalenceClass,
    CapabilityRequirement,
    CapabilityRuntimeContext,
    CapabilitySelectionPolicy,
    ExecutionCapabilityRequest,
)
from personal_agent.runtime.capability_grants import CapabilityGrantIssuer
from personal_agent.capabilities.portfolio import CapabilityPortfolio
from personal_agent.capabilities.resolver import CapabilityResolver
from personal_agent.governance.contracts.audit import DecisionAuditRecord
from personal_agent.governance.decision_admission import (
    AcceptedIntentCompiler,
    DecisionValidator,
    ExecutionCommandResolver,
)
from personal_agent.infra.storage.postgres_control_plane_store import (
    ImmutableCommandConflict,
    PostgresControlPlaneStore,
)
from personal_agent.kernel.contracts.derivation import (
    DerivationInvariantResults,
    DerivationRecord,
)
from personal_agent.planning.task_analyzer import (
    Goal,
    GoalConstraintDraft,
    ResourceHint,
    SuccessCriterionDraft,
    TaskAnalysis,
)
from personal_agent.planning.task_compiler import GoalGraphCompiler
from personal_agent.runtime.contracts.control import (
    BoundedAction,
    CapabilityActionInput,
    ControlProposal,
    ExecuteBoundedActionDecision,
    ModelGroundingClaim,
    ProposedResourceAccessPlan,
    ResourceAccess,
    canonical_digest,
)
from tests.conftest import POSTGRES_URL


def _mutation_chain():
    payload = "Orion 发布窗口是周五 20:00"
    compilation = GoalGraphCompiler().compile(TaskAnalysis(
        user_goal=f"记住：{payload}",
        goals=[Goal(
            goal_id="goal_1",
            description=payload,
            result_contract="external_state",
            success_criteria=[SuccessCriterionDraft(
                description="指定事实已写入知识库",
                origin="model_inferred",
            )],
            constraints=[GoalConstraintDraft(
                description=payload,
                origin="user_explicit",
            )],
            side_effect_intent="mutation",
            resource_hints=[ResourceHint(
                semantic_domain="knowledge",
                resource_types=["text"],
                operations=["ingest"],
            )],
        )],
    ), payload)
    action = BoundedAction(
        goal_id="goal_1",
        execution_intent="commit",
        description="写入指定事实",
        output_contract="MutationReceipt",
        requirement=CapabilityRequirement.from_dimensions(
            requirement_id="knowledge-ingest",
            purpose="ingest exact fact",
            semantic_domains=("knowledge",),
            resource_types=("text",),
            operations=("ingest",),
            output_contract="MutationReceipt",
        ),
        proposed_resource_access=ProposedResourceAccessPlan(
            write_set=(ResourceAccess(semantic_domain="knowledge"),),
            side_effect_class="mutation",
            authority_scope="memory:write",
            data_egress_class="none",
            trust_floor="trusted",
            freshness_contract="current",
            evidence_contract="mutation_receipt",
            failure_semantics="return_typed_failure",
        ),
        input=CapabilityActionInput(task_text=payload),
    )
    decision = ExecuteBoundedActionDecision(
        target_goal_id="goal_1",
        bounded_action=action,
    )
    return payload, compilation.task_contract, compilation.runtime, decision


def _claim(task, payload: str) -> ModelGroundingClaim:
    return ModelGroundingClaim(
        source_ref="constraint:goal_1:constraint:1",
        transform="identity",
        origin="source_identity",
        output_field_ref="bounded_action.input.task_text",
        source_digest=canonical_digest(payload),
    )


def _provider_derivation(binding_ref: str) -> DerivationRecord:
    return DerivationRecord(
        derivation_kind="provider_binding",
        source_contract_refs=("equivalence-class",),
        rule_id="capability-equivalence-binding",
        rule_version="v1",
        policy_snapshot_ref="capability-policy:v1",
        source_digests=("equivalence-digest",),
        output_ref=binding_ref,
        output_digest=canonical_digest(binding_ref),
        invariant_results=DerivationInvariantResults(provider_equivalence="passed"),
        uniqueness_kind="single_active_equivalent_provider",
    )


def test_missing_grounding_is_denied_without_rewriting_proposal() -> None:
    _payload, task, runtime, decision = _mutation_chain()
    proposal = ControlProposal(
        base_task_revision=task.revision,
        base_runtime_revision=runtime.revision,
        decision=decision,
    )

    admission = DecisionValidator().admit(task, runtime, proposal)

    assert admission.verdict == "not_accepted"
    assert admission.reason_codes == ("grounding_required",)
    assert admission.feedback is not None
    assert admission.feedback.revision_scope == "grounding_only"
    assert proposal.decision is decision


def test_grounding_only_revision_preserves_intent_and_is_readmitted() -> None:
    payload, task, runtime, decision = _mutation_chain()
    first = ControlProposal(
        base_task_revision=task.revision,
        base_runtime_revision=runtime.revision,
        decision=decision,
    )
    denial = DecisionValidator().admit(task, runtime, first)
    feedback = denial.feedback
    assert feedback is not None
    revised = ControlProposal(
        base_task_revision=task.revision,
        base_runtime_revision=runtime.revision,
        decision=decision,
        grounding_claims=(_claim(task, payload),),
        supersedes_proposal_ref=first.proposal_id,
        revision_feedback_ref=feedback.feedback_id,
        revision_attempt=1,
    )

    admission = DecisionValidator().admit(
        task,
        runtime,
        revised,
        prior_proposal=first,
        revision_feedback=feedback,
    )

    assert revised.intent_semantic_hash == first.intent_semantic_hash
    assert revised.submission_hash != first.submission_hash
    assert admission.verdict == "accepted"
    intent = AcceptedIntentCompiler().compile(task, runtime, revised, admission)
    assert intent.decision == revised.decision
    assert intent.semantic_digest == revised.intent_semantic_hash


def test_identity_grounding_mismatch_fails_before_execution() -> None:
    payload, task, runtime, decision = _mutation_chain()
    wrong = decision.model_copy(update={
        "bounded_action": decision.bounded_action.model_copy(update={
            "input": CapabilityActionInput(task_text="被模型改写的错误事实"),
        }),
    })
    proposal = ControlProposal(
        base_task_revision=task.revision,
        base_runtime_revision=runtime.revision,
        decision=wrong,
        grounding_claims=(_claim(task, payload),),
    )

    admission = DecisionValidator().admit(task, runtime, proposal)

    assert admission.verdict == "not_accepted"
    assert admission.reason_codes == ("grounding_identity_mismatch",)


def test_scope_expanded_model_decision_is_denied_without_resource_rewrite() -> None:
    payload, task, runtime, decision = _mutation_chain()
    expanded = decision.model_copy(update={
        "bounded_action": decision.bounded_action.model_copy(update={
            "proposed_resource_access": (
                decision.bounded_action.proposed_resource_access.model_copy(update={
                    "write_set": (ResourceAccess(
                        semantic_domain="private_admin",
                        locator="tenant:other",
                    ),),
                })
            ),
        }),
    })
    proposal = ControlProposal(
        base_task_revision=task.revision,
        base_runtime_revision=runtime.revision,
        decision=expanded,
        grounding_claims=(_claim(task, payload),),
    )

    admission = DecisionValidator().admit(task, runtime, proposal)

    assert admission.verdict == "not_accepted"
    assert admission.reason_codes == ("resource_scope_expanded",)
    assert admission.feedback is not None
    assert admission.feedback.disposition == "revise_model"
    assert expanded.bounded_action.proposed_resource_access.write_set == (
        ResourceAccess(semantic_domain="private_admin", locator="tenant:other"),
    )


def test_user_explicit_read_locator_cannot_be_omitted_by_control_proposal() -> None:
    note_id = str(uuid4())
    compilation = GoalGraphCompiler().compile(TaskAnalysis(
        user_goal=f"read note {note_id}",
        goals=[Goal(
            goal_id="goal_1",
            description="read the specified note",
            result_contract="response",
            success_criteria=[SuccessCriterionDraft(
                description="return the note fact",
                origin="model_inferred",
            )],
            resource_hints=[ResourceHint(
                semantic_domain="knowledge",
                resource_types=["note"],
                operations=["read"],
                locator=note_id,
                origin="user_explicit",
            )],
        )],
    ), f"read note {note_id}")
    action = BoundedAction(
        goal_id="goal_1",
        execution_intent="reason",
        description="answer without reading",
        output_contract="VerifiedAnswer",
        proposed_resource_access=ProposedResourceAccessPlan(
            side_effect_class="none",
            authority_scope="response",
            data_egress_class="content",
            trust_floor="external",
            freshness_contract="current",
            evidence_contract="none",
            failure_semantics="return_typed_failure",
        ),
        input=CapabilityActionInput(task_text="answer"),
    )
    proposal = ControlProposal(
        base_task_revision=compilation.task_contract.revision,
        base_runtime_revision=compilation.runtime.revision,
        decision=ExecuteBoundedActionDecision(
            target_goal_id="goal_1",
            bounded_action=action,
        ),
        grounding_claims=(ModelGroundingClaim(
            source_ref="goal:goal_1:goal_id",
            transform="identity",
            origin="source_identity",
            output_field_ref="decision.target_goal_id",
            source_digest=canonical_digest("goal_1"),
        ),),
    )

    admission = DecisionValidator().admit(
        compilation.task_contract, compilation.runtime, proposal,
    )

    assert admission.verdict == "not_accepted"
    assert admission.reason_codes == ("required_resource_scope_missing",)
    assert action.proposed_resource_access.read_set == ()


def test_resource_access_without_capability_is_denied_without_internal_routing() -> None:
    note_id = str(uuid4())
    compilation = GoalGraphCompiler().compile(TaskAnalysis(
        user_goal=f"read note {note_id}",
        goals=[Goal(
            goal_id="goal_1",
            description="read the specified note",
            result_contract="response",
            success_criteria=[SuccessCriterionDraft(
                description="return the note fact",
                origin="model_inferred",
            )],
            resource_hints=[ResourceHint(
                semantic_domain="knowledge",
                resource_types=["note"],
                operations=["read"],
                locator=note_id,
                origin="user_explicit",
            )],
        )],
    ), f"read note {note_id}")
    action = BoundedAction(
        goal_id="goal_1",
        execution_intent="reason",
        description="claim to read without a provider",
        output_contract="VerifiedAnswer",
        requirement=None,
        max_tool_calls=0,
        proposed_resource_access=ProposedResourceAccessPlan(
            read_set=(ResourceAccess(semantic_domain="knowledge", locator=note_id),),
            side_effect_class="none",
            authority_scope="goal:goal_1",
            data_egress_class="content",
            trust_floor="external",
            freshness_contract="current",
            evidence_contract="provider_result",
            failure_semantics="return_typed_failure",
        ),
        input=CapabilityActionInput(task_text="read the note"),
    )
    proposal = ControlProposal(
        base_task_revision=compilation.task_contract.revision,
        base_runtime_revision=compilation.runtime.revision,
        decision=ExecuteBoundedActionDecision(
            target_goal_id="goal_1",
            bounded_action=action,
        ),
        grounding_claims=(ModelGroundingClaim(
            source_ref="goal:goal_1:goal_id",
            transform="identity",
            origin="source_identity",
            output_field_ref="decision.target_goal_id",
            source_digest=canonical_digest("goal_1"),
        ),),
    )

    admission = DecisionValidator().admit(
        compilation.task_contract, compilation.runtime, proposal,
    )

    assert admission.verdict == "not_accepted"
    assert admission.reason_codes == ("resource_access_requires_capability",)
    assert admission.feedback is not None
    assert admission.feedback.disposition == "revise_model"
    assert action.requirement is None
    assert action.proposed_resource_access.read_set == (
        ResourceAccess(semantic_domain="knowledge", locator=note_id),
    )


def test_user_required_provider_cannot_be_omitted_by_control_proposal() -> None:
    compilation = GoalGraphCompiler().compile(TaskAnalysis(
        user_goal="通过 provider ZetaCloud 读取 Q-7319",
        goals=[Goal(
            goal_id="goal_1",
            description="读取指定实验记录",
            result_contract="response",
            success_criteria=[SuccessCriterionDraft(
                description="返回实验记录原文",
                origin="model_inferred",
            )],
            resource_hints=[ResourceHint(
                semantic_domain="experiment",
                resource_types=["record"],
                operations=["search", "read"],
                locator="Q-7319",
                user_required_provider="ZetaCloud",
                origin="user_explicit",
                freshness_required=True,
            )],
        )],
    ), "通过 provider ZetaCloud 读取 Q-7319")
    action = BoundedAction(
        goal_id="goal_1",
        execution_intent="verify",
        description="读取指定实验记录",
        output_contract="VerifiedAnswer",
        requirement=CapabilityRequirement.from_dimensions(
            requirement_id="goal_1",
            purpose="读取指定实验记录",
            semantic_domains=("experiment",),
            resource_types=("record",),
            operations=("search", "read"),
            resource_locator="Q-7319",
            freshness_required=True,
            output_contract="VerifiedAnswer",
        ),
        proposed_resource_access=ProposedResourceAccessPlan(
            read_set=(ResourceAccess(semantic_domain="experiment", locator="Q-7319"),),
            side_effect_class="none",
            authority_scope="goal:goal_1",
            data_egress_class="content",
            trust_floor="external",
            freshness_contract="current",
            evidence_contract="VerifiedAnswer",
            failure_semantics="return_typed_failure",
        ),
        input=CapabilityActionInput(task_text="读取 Q-7319", agentic_synthesis=True),
    )
    proposal = ControlProposal(
        base_task_revision=compilation.task_contract.revision,
        base_runtime_revision=compilation.runtime.revision,
        decision=ExecuteBoundedActionDecision(
            target_goal_id="goal_1",
            bounded_action=action,
        ),
        grounding_claims=(ModelGroundingClaim(
            source_ref="goal:goal_1:goal_id",
            transform="identity",
            origin="source_identity",
            output_field_ref="decision.target_goal_id",
            source_digest=canonical_digest("goal_1"),
        ),),
    )

    admission = DecisionValidator().admit(
        compilation.task_contract, compilation.runtime, proposal,
    )

    assert admission.verdict == "not_accepted"
    assert admission.reason_codes == ("required_provider_scope_missing",)
    assert action.requirement is not None
    assert action.requirement.required_providers == ()


def test_admission_accepts_full_decision_root_for_goal_identity_grounding() -> None:
    _payload, task, runtime, decision = _mutation_chain()
    claim = ModelGroundingClaim(
        source_ref="goal:goal_1:goal_id",
        transform="identity",
        origin="source_identity",
        output_field_ref="decision.target_goal_id",
        source_digest=canonical_digest("goal_1"),
    )
    proposal = ControlProposal(
        base_task_revision=task.revision,
        base_runtime_revision=runtime.revision,
        decision=decision,
        grounding_claims=(claim,),
    )

    admission = DecisionValidator().admit(task, runtime, proposal)

    assert admission.verdict == "accepted"


def test_provider_rebinding_changes_command_not_authorization() -> None:
    payload, task, runtime, decision = _mutation_chain()
    proposal = ControlProposal(
        base_task_revision=task.revision,
        base_runtime_revision=runtime.revision,
        decision=decision,
        grounding_claims=(_claim(task, payload),),
    )
    admission = DecisionValidator().admit(task, runtime, proposal)
    intent = AcceptedIntentCompiler().compile(task, runtime, proposal, admission)
    resolver = ExecutionCommandResolver()
    first = resolver.resolve(
        task,
        intent,
        provider_binding_refs=("provider:a",),
        provider_binding_derivations=(_provider_derivation("provider:a"),),
    )
    rebound = resolver.resolve(
        task,
        intent,
        provider_binding_refs=("provider:b",),
        provider_binding_derivations=(_provider_derivation("provider:b"),),
        supersedes_command_ref=first.command_id,
    )

    assert rebound.supersedes_command_ref == first.command_id
    assert rebound.authorization_digest == first.authorization_digest
    assert rebound.execution_command_digest != first.execution_command_digest


def test_grant_is_issued_only_after_provider_bound_command() -> None:
    payload, task, runtime, decision = _mutation_chain()
    proposal = ControlProposal(
        base_task_revision=task.revision,
        base_runtime_revision=runtime.revision,
        decision=decision,
        grounding_claims=(_claim(task, payload),),
    )
    admission = DecisionValidator().admit(task, runtime, proposal)
    intent = AcceptedIntentCompiler().compile(task, runtime, proposal, admission)
    base_command = ExecutionCommandResolver().resolve(task, intent)
    capability = Capability.from_dimensions(
        capability_id="knowledge-writer",
        kind="local_tool",
        provider="memory",
        local_name="memory.ingest",
        semantic_domains=("knowledge",),
        resource_types=("text",),
        operations=("ingest",),
        side_effects=("mutation",),
        output_contract="MutationReceipt",
        auth_scope="memory:write",
        trust_level="trusted",
        credential_mode="none",
        data_egress_class="none",
        attestation_status="verified",
        freshness_profile="realtime",
        evidence_contract="mutation_receipt",
        failure_semantics="return_typed_failure",
        metadata_source="system",
    )
    request = ExecutionCapabilityRequest(
        task_id=task.task_id,
        task_revision=task.revision,
        goal_id="goal_1",
        action_id=decision.bounded_action.action_id,
        execution_intent="commit",
        allowed_kinds=("local_tool",),
        allowed_operations=("ingest",),
        policy=CapabilitySelectionPolicy(read_only=False),
        requirements=(decision.bounded_action.requirement,),
        runtime_context=CapabilityRuntimeContext(
            equivalence_class=CapabilityEquivalenceClass(
                required_output_contract="MutationReceipt",
                allowed_side_effect_class="mutation",
                authority_scope="memory:write",
                trust_floor="trusted",
                freshness_contract="current",
                evidence_contract="mutation_receipt",
                data_egress_class="none",
                failure_semantics="return_typed_failure",
            ),
        ),
    )
    resolution = CapabilityResolver(CapabilityPortfolio((capability,))).resolve(request)
    assert resolution.selected_definition == capability
    binding_ref = "memory:memory.ingest"
    final_command = ExecutionCommandResolver().resolve(
        task,
        intent,
        supersedes_command_ref=base_command.command_id,
        provider_binding_refs=(binding_ref,),
        provider_binding_derivations=(resolution.decision.derivation_record,),
    )

    grant = CapabilityGrantIssuer().issue(request, capability, final_command)

    assert grant.execution_command_digest == final_command.execution_command_digest
    assert grant.execution_command_digest != base_command.execution_command_digest
    assert grant.provider_binding_ref == binding_ref


def test_command_store_replays_persisted_command_and_rejects_overwrite() -> None:
    payload, task, runtime, decision = _mutation_chain()
    proposal = ControlProposal(
        base_task_revision=task.revision,
        base_runtime_revision=runtime.revision,
        decision=decision,
        grounding_claims=(_claim(task, payload),),
    )
    admission = DecisionValidator().admit(task, runtime, proposal)
    intent = AcceptedIntentCompiler().compile(task, runtime, proposal, admission)
    command = ExecutionCommandResolver().resolve(task, intent)
    store = PostgresControlPlaneStore(POSTGRES_URL)

    store.put_command("run-command-replay", command)
    restored = store.get_command(command.command_id)

    assert restored == command
    changed = command.model_copy(update={"execution_command_digest": "different"})
    with pytest.raises(ImmutableCommandConflict):
        store.put_command("run-command-replay", changed)


def test_denied_proposal_is_persisted_only_in_decision_audit() -> None:
    _payload, task, runtime, decision = _mutation_chain()
    proposal = ControlProposal(
        base_task_revision=task.revision,
        base_runtime_revision=runtime.revision,
        decision=decision,
    )
    admission = DecisionValidator().admit(task, runtime, proposal)
    run_id = f"run-denied-audit-{uuid4().hex}"
    record = DecisionAuditRecord(
        run_id=run_id,
        turn_ref="turn-1",
        proposal=proposal,
        admission=admission,
    )
    store = PostgresControlPlaneStore(POSTGRES_URL)

    store.append_decision_audit(record)

    assert store.list_decision_audit(run_id, DecisionAuditRecord) == (record,)
    with store._connect() as conn:  # noqa: SLF001 - architecture ownership assertion
        count = conn.execute(
            "SELECT count(*) FROM canonical_domain_events WHERE run_id = %s",
            (run_id,),
        ).fetchone()[0]
    assert count == 0
