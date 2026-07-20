"""Issue execution grants only after a provider-bound command is immutable."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from personal_agent.capabilities.contracts.execution import Capability, ExecutionCapabilityRequest
from personal_agent.capabilities.contracts.grants import (
    AtomicCapabilityGrant,
    AvailabilityDependency,
    DelegationGrant,
    ExecutionGrant,
    GrantDependencySet,
)
from personal_agent.runtime.contracts.control import ResolvedExecutionCommand


class CapabilityGrantIssuer:
    """Create the leaf authority fence for one exact resolved command."""

    def issue(
        self,
        request: ExecutionCapabilityRequest,
        capability: Capability,
        command: ResolvedExecutionCommand,
    ) -> ExecutionGrant:
        provider_binding_ref = f"{capability.provider}:{capability.local_name or capability.capability_id}"
        if provider_binding_ref not in command.provider_binding_refs:
            raise ValueError("grant provider is not bound by the execution command")
        requirement = request.requirements[0] if request.requirements else None
        selector = requirement.selector if requirement is not None else capability.selector
        requested_operations = set(request.allowed_operations)
        if requirement is not None:
            requested_operations &= set(requirement.operation_scope.operations)
        granted_operations = capability.operation_scope.model_copy(update={
            "operations": frozenset(set(capability.operations) & requested_operations),
            "side_effect_class": (
                requirement.operation_scope.side_effect_class
                if requirement is not None else capability.operation_scope.side_effect_class
            ),
        })
        valid_until = min(command.expires_at, datetime.now(UTC) + timedelta(minutes=10))
        dependencies = GrantDependencySet(
            task_revision=request.task_revision,
            goal_definition_fingerprint=sha256(request.goal_id.encode()).hexdigest()[:16],
            action_fingerprint=sha256(
                f"{request.action_id}:{request.execution_intent}".encode()
            ).hexdigest()[:16],
            capability_definition_revision=capability.definition_revision,
            provider_binding_revision=request.runtime_context.provider_binding_revision,
            availability_dependencies=(AvailabilityDependency(
                capability_ref=capability.capability_id,
                availability_revision=request.runtime_context.availability_revision,
                valid_until=valid_until,
            ),),
            authority_revision=request.runtime_context.authority_revision,
            policy_bundle_hash=sha256(request.policy_profile_ref.encode()).hexdigest()[:16],
        )
        common = dict(
            request_id=str(request.request_id),
            action_ref=request.action_id,
            authorization_digest=command.authorization_digest,
            execution_command_digest=command.execution_command_digest,
            granted_resource_selector=selector,
            granted_operation_scope=granted_operations,
            granted_data_egress=capability.data_egress_class,
            granted_credential_mode=capability.credential_mode,
            retry_family_id=f"retry:{request.action_id}",
            dependency_set=dependencies,
            expires_at=valid_until,
        )
        if capability.kind == "agent":
            return DelegationGrant(
                **common,
                agent_binding_ref=provider_binding_ref,
                bounded_sub_goal=request.runtime_context.bounded_sub_goal or request.execution_intent,
                context_projection_refs=request.runtime_context.context_projection_refs,
                token_budget=request.runtime_context.token_budget,
                cost_budget=request.runtime_context.cost_budget,
                time_budget_seconds=request.runtime_context.time_budget_seconds,
                max_delegation_depth=request.runtime_context.max_delegation_depth,
                completion_contract=request.runtime_context.completion_contract,
            )
        return AtomicCapabilityGrant(
            **common,
            capability_ref=capability.capability_id,
            provider_binding_ref=provider_binding_ref,
        )


__all__ = ["CapabilityGrantIssuer"]
