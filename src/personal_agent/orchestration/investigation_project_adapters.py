"""Composition-edge adapters from existing capability owners into Project ports."""

from __future__ import annotations

import hashlib
import json

from personal_agent.agents.gateway import AgentGateway, AgentSubmissionOutcomeUnknown
from personal_agent.application.investigation_project.ports import (
    CapabilitySnapshotPort,
    DelegationPolicyDecision,
    ExecutionResult,
    GeneratedArtifactWritePort,
    ProjectAgentOutcomeUnknown,
)
from personal_agent.capabilities.contracts.grants import (
    DelegationGrant,
    GrantDependencySet,
)
from personal_agent.capabilities.inventory import RuntimeCapabilityInventory
from personal_agent.domain.investigation_project import (
    DisclosureManifest,
    EvidenceRef,
    ExecutionRef,
    ProjectUsage,
    SubGoalExecutionProposal,
    canonical_digest,
)
from personal_agent.governance.policy import PolicyEngine, PolicyInput
from personal_agent.governance.registry import ToolExecutor
from personal_agent.kernel.contracts.agent import AgentGatewayContext, AgentTask
from personal_agent.kernel.contracts.resource import (
    OperationScope,
    ResourceRef,
    ResourceSelector,
)
from personal_agent.kernel.contracts.scope import ExecutionScope, AuthenticatedPrincipal


class RuntimeCapabilitySnapshot(CapabilitySnapshotPort):
    def __init__(self, inventory_factory) -> None:
        self._inventory_factory = inventory_factory

    def snapshot(self, owner: AuthenticatedPrincipal) -> RuntimeCapabilityInventory:
        inventory = self._inventory_factory()
        if not isinstance(inventory, RuntimeCapabilityInventory):
            raise TypeError("capability factory returned an invalid inventory")
        return inventory

    def revision(self, inventory: RuntimeCapabilityInventory) -> str:
        return canonical_digest(inventory.model_dump(mode="json"))


class ToolExecutorProjectAdapter:
    def __init__(
        self,
        executor: ToolExecutor,
        artifact_writer: GeneratedArtifactWritePort,
    ) -> None:
        self._executor = executor
        self._artifact_writer = artifact_writer

    def execute(
        self,
        proposal: SubGoalExecutionProposal,
        *,
        execution_scope: ExecutionScope,
    ) -> ExecutionResult:
        operation = proposal.operation
        if operation.kind != "tool":
            raise TypeError("tool adapter received a non-tool proposal")
        output = self._executor.invoke_project(
            operation.tool_name,
            operation.typed_arguments,
            execution_scope=execution_scope,
            tool_call_id=proposal.proposal_id,
            proposal_digest=proposal.proposal_digest,
        )
        if not output.get("ok"):
            raise RuntimeError(
                str(output.get("error") or f"tool {operation.tool_name} failed")
            )
        execution_digest = canonical_digest({
            "proposal_digest": proposal.proposal_digest,
            "tool": operation.tool_name,
            "output": output,
        })
        execution_ref = ExecutionRef(
            execution_id=execution_scope.execution_id,
            execution_kind="tool",
            owner_ref=proposal.proposal_id,
            execution_digest=execution_digest,
        )
        artifact_refs = _artifact_refs(output, execution_scope.principal)
        evidence_payload = {
            "tool": operation.tool_name,
            "data": output.get("data"),
            "evidence": output.get("evidence") or [],
        }
        content = json.dumps(
            evidence_payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        content_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        evidence_artifact_ref = self._artifact_writer.write_generated(
            owner=execution_scope.principal,
            execution_scope=execution_scope,
            producer_key=(
                f"tool-evidence:{proposal.proposal_digest}:{content_digest}"
            ),
            producer_ref=execution_ref.execution_id,
            kind="tool_evidence",
            content=content,
            content_digest=content_digest,
            source_artifact_refs=artifact_refs,
            evidence_refs=(),
        )
        evidence = EvidenceRef(
            evidence_id=f"ipev_{content_digest[:20]}",
            execution_ref=execution_ref,
            artifact_ref=evidence_artifact_ref,
            source=f"tool:{operation.tool_name}",
            content_digest=content_digest,
            summary=content[:500],
        )
        return ExecutionResult(
            execution_ref=execution_ref,
            evidence=(evidence,),
            artifact_refs=(*artifact_refs, evidence_artifact_ref),
            usage=ProjectUsage(
                category="execution_proposal",
                reservation_id=f"tool:{proposal.proposal_digest}",
                tool_calls=1,
            ),
        )


class PolicyEngineDelegationAdapter:
    def __init__(self, policy: PolicyEngine, profile_lookup) -> None:
        self._policy = policy
        self._profile_lookup = profile_lookup

    def evaluate(
        self,
        proposal: SubGoalExecutionProposal,
        *,
        execution_scope: ExecutionScope,
    ) -> DelegationPolicyDecision:
        operation = proposal.operation
        if operation.kind != "agent":
            raise TypeError("delegation policy received a non-agent proposal")
        profile = self._profile_lookup(operation.agent_id)
        if profile is None:
            return DelegationPolicyDecision(
                allowed=False,
                requires_approval=False,
                authorization_digest=canonical_digest({
                    "proposal": proposal.proposal_digest,
                    "effect": "deny",
                    "reason": "agent_profile_missing",
                }),
                reason="agent profile is not registered",
            )
        decision = self._policy.evaluate(PolicyInput(
            action="agent_call",
            user_id=execution_scope.principal.principal_id,
            execution_mode="deterministic",
            tool_name=operation.agent_id,
            risk_level=profile.governance.risk_level,
            side_effects=profile.governance.side_effects,
            permission_scope=profile.governance.permission_scope,
            confirmed=False,
        ))
        authorization_digest = canonical_digest({
            "proposal": proposal.proposal_digest,
            "scope": execution_scope.model_dump(mode="json"),
            "effect": decision.effect,
            "rule": decision.rule,
        })
        return DelegationPolicyDecision(
            allowed=decision.allowed or decision.needs_confirmation,
            requires_approval=decision.needs_confirmation,
            authorization_digest=authorization_digest,
            reason=decision.reason,
        )


class ScopeBoundDisclosureManifest:
    def materialize(
        self,
        artifact_refs: tuple[ResourceRef, ...],
        *,
        owner: AuthenticatedPrincipal,
        execution_scope: ExecutionScope,
    ) -> DisclosureManifest:
        if execution_scope.principal != owner:
            raise PermissionError("disclosure execution scope mismatch")
        if any(item.owner != owner for item in artifact_refs):
            raise PermissionError("disclosure contains cross-scope artifacts")
        content_digest = canonical_digest({
            "owner": owner.model_dump(mode="json"),
            "artifact_refs": [item.model_dump(mode="json") for item in artifact_refs],
            "redaction_policy": "private_excerpt",
        })
        return DisclosureManifest(
            artifact_refs=artifact_refs,
            allowed_sections=("bounded_excerpt",),
            redaction_policy="private_excerpt",
            content_digest=content_digest,
        )


class DurableProjectAgentAdapter:
    """Project adapter over the canonical durable AgentGateway lifecycle."""

    def __init__(self, gateway: AgentGateway) -> None:
        self._gateway = gateway

    def submit_or_reconcile(
        self,
        proposal: SubGoalExecutionProposal,
        *,
        execution_scope: ExecutionScope,
        submission_key: str,
        authorization_digest: str | None = None,
        execution_command_digest: str | None = None,
    ) -> ExecutionResult:
        operation = proposal.operation
        if operation.kind != "agent":
            raise TypeError("agent adapter received a non-agent proposal")
        context = AgentGatewayContext(
            execution_scope=execution_scope.model_copy(
                update={"task_id": proposal.proposal_id}
            ),
            source_platform="investigation_project",
            confirmed=execution_command_digest is not None,
        )
        grant = DelegationGrant(
            request_id=proposal.proposal_id,
            action_ref=proposal.proposal_id,
            authorization_digest=authorization_digest or proposal.proposal_digest,
            execution_command_digest=(
                execution_command_digest or proposal.proposal_digest
            ),
            granted_resource_selector=ResourceSelector(),
            granted_operation_scope=OperationScope(
                operations=frozenset({"delegate"}),
                side_effect_class="external_network",
            ),
            granted_data_egress="content",
            granted_credential_mode="provider",
            retry_family_id=submission_key,
            dependency_set=GrantDependencySet(
                task_revision=proposal.subgoal_version,
                goal_definition_fingerprint=proposal.logical_subgoal_id,
                action_fingerprint=proposal.proposal_digest,
                plan_id=proposal.project_id,
                plan_revision=proposal.plan_version,
                step_fingerprint=proposal.proposal_digest,
                capability_definition_revision=1,
                authority_revision=1,
                policy_bundle_hash=authorization_digest or proposal.proposal_digest,
            ),
            agent_binding_ref=f"project:{operation.agent_id}",
            bounded_sub_goal=operation.bounded_sub_goal,
            context_projection_refs=tuple(
                item.resource_id for item in operation.context_artifact_refs
            ),
            token_budget=max(operation.token_budget, 1),
            cost_budget=operation.cost_budget,
            time_budget_seconds=operation.time_budget_seconds,
            completion_contract="AgentArtifact",
        )
        try:
            run = self._gateway.submit(
                operation.agent_id,
                AgentTask(
                    task_text=operation.bounded_sub_goal,
                    task_type="research",
                    metadata={
                        "expected_artifact_types": operation.expected_artifact_types,
                        "context_artifact_refs": [
                            item.model_dump(mode="json")
                            for item in operation.context_artifact_refs
                        ],
                    },
                ),
                context,
                grant,
                submission_key=submission_key,
            )
        except AgentSubmissionOutcomeUnknown as exc:
            raise ProjectAgentOutcomeUnknown(str(exc)) from exc
        if run.projection.status in {"created", "queued", "running", "waiting"}:
            run = self._gateway.poll(run.definition.agent_run_id, context)
        if run.projection.status in {"created", "queued", "running", "waiting"}:
            return ExecutionResult(
                execution_ref=_agent_execution_ref(
                    proposal, run.definition.agent_run_id, run.projection.result
                ),
                evidence=(),
                pending=True,
                provider_task_ref=run.definition.agent_run_id,
                submission_key=submission_key,
            )
        if run.projection.status not in {"completed", "completed_degraded"}:
            raise RuntimeError(
                run.projection.error
                or f"child Agent ended with status={run.projection.status}"
            )
        execution_ref = _agent_execution_ref(
            proposal, run.definition.agent_run_id, run.projection.result
        )
        evidence: list[EvidenceRef] = []
        for artifact in run.artifact_index.artifacts:
            body_digest = canonical_digest({
                "kind": artifact.kind,
                "artifact_ref": artifact.artifact_ref.model_dump(mode="json"),
            })
            evidence.append(EvidenceRef(
                evidence_id=f"ipev_{body_digest[:20]}",
                execution_ref=execution_ref,
                artifact_ref=artifact.artifact_ref,
                source=f"agent:{operation.agent_id}",
                content_digest=body_digest,
                summary=f"{artifact.kind}:{artifact.artifact_ref.resource_id}",
            ))
        return ExecutionResult(
            execution_ref=execution_ref,
            evidence=tuple(evidence),
            artifact_refs=tuple(
                item.artifact_ref for item in run.artifact_index.artifacts
            ),
            usage=ProjectUsage(
                category="external_delegation",
                reservation_id=f"agent:{proposal.proposal_digest}",
                agent_calls=1,
            ),
            submission_key=submission_key,
        )

    def cancel(
        self,
        agent_run_id: str,
        *,
        execution_scope: ExecutionScope,
    ) -> tuple[ResourceRef, ...]:
        run = self._gateway.get_run(agent_run_id)
        if run is None:
            return ()
        cancelled = self._gateway.cancel(agent_run_id, run.definition.context)
        return tuple(
            item.artifact_ref for item in cancelled.artifact_index.artifacts
        )


def _agent_execution_ref(
    proposal: SubGoalExecutionProposal,
    agent_run_id: str,
    result: dict,
) -> ExecutionRef:
    return ExecutionRef(
        execution_id=agent_run_id,
        execution_kind="agent",
        owner_ref=proposal.proposal_id,
        execution_digest=canonical_digest({
            "proposal_digest": proposal.proposal_digest,
            "agent_run_id": agent_run_id,
            "result": result,
        }),
    )


def _artifact_refs(
    output: dict,
    expected_scope: AuthenticatedPrincipal,
) -> tuple[ResourceRef, ...]:
    candidates: list[object] = []
    data = output.get("data")
    if isinstance(data, dict):
        if data.get("resource_ref") is not None:
            candidates.append(data["resource_ref"])
        candidates.extend(data.get("artifact_refs") or [])
    parsed: list[ResourceRef] = []
    for item in candidates:
        ref = ResourceRef.model_validate(item)
        if ref.owner != expected_scope:
            raise PermissionError("tool returned cross-scope artifact")
        parsed.append(ref)
    return tuple(parsed)


__all__ = [
    "DurableProjectAgentAdapter",
    "PolicyEngineDelegationAdapter",
    "RuntimeCapabilitySnapshot",
    "ScopeBoundDisclosureManifest",
    "ToolExecutorProjectAdapter",
]
