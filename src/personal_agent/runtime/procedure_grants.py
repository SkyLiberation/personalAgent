"""Derive procedure child grants without widening the parent envelope."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from personal_agent.capabilities.contracts.grants import (
    AtomicCapabilityGrant,
    GrantDependencySet,
    ProcedureGrant,
    ProcedureNodeGrant,
)
from personal_agent.capabilities.contracts.procedure import (
    ProcedureDefinition,
    ProcedureInvocation,
    ProcedureRunProjection,
)
from personal_agent.execution.contracts.invocation import ExecutableInvocation
from personal_agent.kernel.contracts.resource import OperationScope, ResourceSelector
from personal_agent.runtime.contracts.task import TaskContract
from personal_agent.runtime.contracts.control import ResolvedExecutionCommand


class ProcedureGrantIssuer:
    def issue_start(
        self,
        task: TaskContract,
        invocation: ProcedureInvocation,
        projection: ProcedureRunProjection,
        definition: ProcedureDefinition,
        command: ResolvedExecutionCommand,
    ) -> ProcedureGrant:
        resources = task.resources_for_goal(invocation.goal_id)
        selector = ResourceSelector(
            semantic_domains=frozenset(
                domain for item in resources for domain in item.selector.semantic_domains
            ) | frozenset(
                domain
                for node in definition.nodes
                if node.capability_requirement is not None
                for domain in node.capability_requirement.semantic_domains
            ),
            resource_types=frozenset(
                resource for item in resources for resource in item.selector.resource_types
            ) | frozenset(
                resource
                for node in definition.nodes
                if node.capability_requirement is not None
                for resource in node.capability_requirement.resource_types
            ),
            locator=next((item.locator for item in resources if item.locator), None),
        )
        operation_scope = OperationScope(
            operations=frozenset(
                operation for item in resources for operation in item.required_operations
            ) | frozenset(
                operation
                for node in definition.nodes
                if node.capability_requirement is not None
                for operation in node.capability_requirement.operations
            ),
            side_effect_class="procedure",
        )
        expires_at = datetime.now(UTC) + timedelta(minutes=15)
        dependencies = GrantDependencySet(
            task_revision=task.revision,
            goal_definition_fingerprint=sha256(invocation.goal_id.encode()).hexdigest()[:16],
            action_fingerprint=sha256(invocation.invocation_id.encode()).hexdigest()[:16],
            capability_definition_revision=1,
            authority_revision=1,
            policy_bundle_hash=sha256(b"procedure-policy:v1").hexdigest()[:16],
        )
        return ProcedureGrant(
            request_id=f"procedure:{invocation.invocation_id}",
            action_ref=invocation.invocation_id,
            authorization_digest=command.authorization_digest,
            execution_command_digest=command.execution_command_digest,
            granted_resource_selector=selector,
            granted_operation_scope=operation_scope,
            granted_data_egress="content",
            granted_credential_mode="none",
            # A request id/idempotency key is not proof of user confirmation.
            # Mutation nodes receive a new immutable grant only after HITL resumes.
            required_confirmation_ref=None,
            retry_family_id=f"retry:{invocation.invocation_id}",
            dependency_set=dependencies,
            expires_at=expires_at,
            procedure_id=invocation.procedure.procedure_id,
            procedure_version=invocation.procedure.version,
            permission_envelope_ref=f"procedure-envelope:{projection.procedure_run_id}",
            receipt_contract=invocation.expected_output_contract,
        )

    def derive_node(
        self,
        parent: ProcedureGrant,
        projection: ProcedureRunProjection,
        step: ExecutableInvocation,
        atomic: AtomicCapabilityGrant,
        command: ResolvedExecutionCommand,
    ) -> ProcedureNodeGrant:
        if command.authorization_digest != parent.authorization_digest:
            raise PermissionError("procedure node command expands the parent authorization")
        if atomic.execution_command_digest != command.execution_command_digest:
            raise PermissionError("atomic grant is not bound to the procedure node command")
        child_operations = (
            parent.granted_operation_scope.operations
            & atomic.granted_operation_scope.operations
        )
        if not child_operations:
            raise PermissionError("procedure node grant has no operation inside parent envelope")
        child_domains = (
            parent.granted_resource_selector.semantic_domains
            & atomic.granted_resource_selector.semantic_domains
        )
        child_types = (
            parent.granted_resource_selector.resource_types
            & atomic.granted_resource_selector.resource_types
        )
        if atomic.granted_resource_selector.semantic_domains and not child_domains:
            raise PermissionError("procedure node semantic domain exceeds parent envelope")
        if atomic.granted_resource_selector.resource_types and not child_types:
            raise PermissionError("procedure node resource type exceeds parent envelope")
        parent_locator = parent.granted_resource_selector.locator
        child_locator = atomic.granted_resource_selector.locator
        if parent_locator and child_locator and parent_locator != child_locator:
            raise PermissionError("procedure node locator exceeds parent envelope")
        child_selector = ResourceSelector(
            semantic_domains=child_domains,
            resource_types=child_types,
            locator=child_locator or parent_locator,
        )
        return ProcedureNodeGrant(
            request_id=atomic.request_id,
            action_ref=parent.action_ref,
            authorization_digest=command.authorization_digest,
            execution_command_digest=command.execution_command_digest,
            granted_resource_selector=child_selector,
            granted_operation_scope=atomic.granted_operation_scope.model_copy(update={
                "operations": child_operations,
            }),
            granted_data_egress=atomic.granted_data_egress,
            granted_credential_mode=atomic.granted_credential_mode,
            required_confirmation_ref=parent.required_confirmation_ref,
            retry_family_id=parent.retry_family_id,
            dependency_set=atomic.dependency_set,
            expires_at=min(parent.expires_at, atomic.expires_at),
            procedure_run_id=projection.procedure_run_id,
            node_id=step.procedure_node_id or step.step_id,
            capability_ref=atomic.capability_ref,
            provider_binding_ref=atomic.provider_binding_ref,
        )

    @staticmethod
    def bind_confirmation(grant, confirmation_ref: str):
        if grant.required_confirmation_ref == confirmation_ref:
            return grant
        dependencies = grant.dependency_set.model_copy(update={
            "confirmation_revision": (
                (grant.dependency_set.confirmation_revision or 0) + 1
            ),
        })
        return grant.model_copy(update={
            "grant_id": uuid4().hex,
            "required_confirmation_ref": confirmation_ref,
            "dependency_set": dependencies,
        })


__all__ = ["ProcedureGrantIssuer"]
