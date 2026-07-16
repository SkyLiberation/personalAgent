from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from personal_agent.capabilities.contracts.execution import (
    Capability,
    CapabilityCoverage,
    CapabilityRequirement,
    ExecutionResolutionResult,
    CapabilityResolutionDecision,
    ExecutionCapabilityRequest,
    CapabilitySelectionPolicy,
    DeniedCapability,
    EscalationHint,
)
from personal_agent.capabilities.contracts.grants import (
    AtomicCapabilityGrant,
    AvailabilityDependency,
    DelegationGrant,
    GrantDependencySet,
)
from personal_agent.kernel.contracts.policy import PolicyEvaluator, PolicyInput
from personal_agent.capabilities.admission import ResolutionValidator
from personal_agent.capabilities.outcomes import (
    CapabilityRanker,
    OutcomeAwareCapabilityRanker,
)
from personal_agent.capabilities.portfolio import CapabilityPortfolio
from personal_agent.kernel.contracts.resource import MUTATING_OPERATIONS, match_resource_contract
_TRUST_ORDER = {"untrusted": 0, "external": 1, "scoped": 2, "trusted": 3}


class CapabilityResolver:
    """Resolve structured action requirements against governed capabilities."""

    def __init__(
        self,
        registry: CapabilityPortfolio,
        *,
        policy_engine: PolicyEvaluator | None = None,
        validator: ResolutionValidator | None = None,
        ranker: CapabilityRanker | None = None,
    ) -> None:
        self._registry = registry
        self._policy_engine = policy_engine
        self._validator = validator or ResolutionValidator()
        self._ranker = ranker or OutcomeAwareCapabilityRanker()

    def resolve(self, request: ExecutionCapabilityRequest) -> ExecutionResolutionResult:
        denied: list[DeniedCapability] = []
        candidates: list[Capability] = []
        hard_denied_ids: set[str] = set()
        allowed_kinds = set(request.allowed_kinds)
        allowed_operations = set(request.allowed_operations)
        expected_names = {
            str(item)
            for item in request.runtime_context.get("expected_local_names", ())
            if str(item)
        }

        for capability in self._registry.list():
            reason = self._ineligibility_reason(
                capability,
                request,
                allowed_kinds=allowed_kinds,
                allowed_operations=allowed_operations,
                expected_names=expected_names,
            )
            if reason is not None:
                denied.append(_deny(capability, reason))
                if reason in {
                    "unreviewed_high_risk_metadata",
                    "sensitive_egress_denied",
                    "sensitive_requires_trusted_provider",
                } or reason.startswith("policy:"):
                    hard_denied_ids.add(capability.capability_id)
                continue
            candidates.append(capability)

        candidates, local_denials = _apply_local_first(candidates, request)
        denied.extend(local_denials)
        ranked, ranking_audit = self._ranker.rank(
            candidates,
            request,
            lambda capability: _rank_key(
                capability,
                request.requirements,
                request.policy,
            ),
        )
        # One accepted Action receives one leaf grant. Multi-source discovery
        # belongs to Portfolio selection, not execution authorization.
        selected = ranked[:1]
        selected_ids = {capability.capability_id for capability in selected}
        denied.extend(
            _deny(capability, "policy_clamped")
            for capability in ranked
            if capability.capability_id not in selected_ids
        )
        coverage = _coverage_for_requirements(
            request.requirements,
            selected,
            denied,
            request,
            self._registry.list(),
        )
        errors = self._validator.errors(
            request,
            selected[0] if selected else None,
            tuple(denied),
            hard_denied_ids=frozenset(hard_denied_ids),
        )
        if errors and selected:
            denied.append(_deny(selected[0], "resolution_validator:" + ",".join(errors)))
            selected = []
            coverage = _coverage_for_requirements(
                request.requirements, [], denied, request, self._registry.list(),
            )
        selected_definition = selected[0] if selected else None
        grant = _grant_for(request, selected_definition) if selected_definition else None
        decision = CapabilityResolutionDecision(
            request_id=str(request.request_id),
            discovery_snapshot_ref=_discovery_snapshot_ref(self._registry.list()),
            considered_candidate_refs=tuple(item.capability_id for item in self._registry.list()),
            hard_denial_refs=tuple(sorted(hard_denied_ids)),
            selected_execution_grant_ref=grant.grant_id if grant else None,
            reason_codes=(
                ("resolution_validator_rejected",) if errors else
                ("capability_selected",) if grant else ("capability_unavailable",)
            ),
            validation_state="rejected" if errors else "validated",
        )
        return ExecutionResolutionResult(
            decision=decision,
            selected_definition=selected_definition,
            execution_grant=grant,
            denials=tuple(denied),
            coverage=coverage,
            escalation_hint=_escalation_hint(request, selected),
            rationale=(
                f"selected {selected_definition.capability_id}"
                if selected_definition else "no capability satisfies the current action contract"
            ),
            confidence=0.85 if selected_definition else 0.0 if errors else 0.4,
            ranking_audit=ranking_audit,
            validator_errors=errors,
        )

    def _ineligibility_reason(
        self,
        capability: Capability,
        request: ExecutionCapabilityRequest,
        *,
        allowed_kinds: set[str],
        allowed_operations: set[str],
        expected_names: set[str],
    ) -> str | None:
        if not capability.selectable:
            return "capability_not_selectable"
        if (
            capability.selectable_only_in_actions
            and request.action_id not in capability.selectable_only_in_actions
        ):
            return "not_selectable_in_action"
        if capability.kind not in allowed_kinds:
            return "kind_not_allowed"
        if request.requirements and not any(
            _matches_requirement(capability, requirement)
            for requirement in request.requirements
        ):
            return "requirement_mismatch"
        if expected_names and _capability_local_name(capability) not in expected_names:
            return "not_expected_for_action"
        # A capability descriptor advertises its full operation surface; the
        # request is the actual grant. Select a multi-operation capability for
        # the granted intersection without widening the action scope.
        if allowed_operations and not set(capability.operations).intersection(allowed_operations):
            return "operation_not_allowed"
        if request.policy.read_only and set(capability.operations) & MUTATING_OPERATIONS:
            return "read_only_policy"
        if _metadata_requires_review(capability, request.policy):
            return "unreviewed_high_risk_metadata"
        if request.policy.deny_sensitive_egress and capability.data_egress_class == "sensitive":
            return "sensitive_egress_denied"
        if (
            request.policy.require_trusted_for_sensitive
            and capability.data_egress_class == "sensitive"
            and capability.trust_level not in {"trusted", "scoped"}
        ):
            return "sensitive_requires_trusted_provider"
        policy_decision = self._policy_decision(capability, request)
        if policy_decision is not None and policy_decision.effect in {"deny", "require_escalation"}:
            return f"policy:{policy_decision.rule}"
        return None

    def _policy_decision(
        self,
        capability: Capability,
        request: ExecutionCapabilityRequest,
    ):
        if self._policy_engine is None:
            return None
        if capability.kind == "agent":
            action = "agent_call"
        elif capability.kind == "retriever":
            action = "memory_read"
        else:
            action = "tool_call"
        return self._policy_engine.evaluate(PolicyInput(
            action=action,  # type: ignore[arg-type]
            user_id=_context_str(request, "user_id"),
            session_id=_context_str(request, "session_id"),
            source_platform=_context_str(request, "source_platform"),
            execution_mode="capability_resolution",
            tool_name=_capability_local_name(capability),
            risk_level=capability.risk_level,  # type: ignore[arg-type]
            side_effects=capability.side_effects,  # type: ignore[arg-type]
            permission_scope=capability.auth_scope,
            react_allowed_tools=frozenset(
                request.runtime_context.get("react_allowed_tools", ())
            ),
        ))


def default_capability_policy(
    execution_intent: str,
    *,
    mutating: bool = False,
) -> CapabilitySelectionPolicy:
    if mutating or execution_intent in {"commit", "remember"}:
        return CapabilitySelectionPolicy(
            local_first=False,
            read_only=False,
            max_capabilities_per_action=2,
            max_providers_per_action=1,
        )
    return CapabilitySelectionPolicy(
        local_first=False,
        read_only=True,
        max_capabilities_per_action=4,
        max_providers_per_action=2,
    )


def _apply_local_first(
    candidates: list[Capability],
    request: ExecutionCapabilityRequest,
) -> tuple[list[Capability], list[DeniedCapability]]:
    if not request.policy.local_first:
        return candidates, []
    if any(item.required_providers for item in request.requirements):
        return candidates, []
    local = [capability for capability in candidates if _is_local_capability(capability)]
    if not local:
        return candidates, []
    local_ids = {capability.capability_id for capability in local}
    denied = [
        _deny(capability, "local_first")
        for capability in candidates
        if capability.capability_id not in local_ids
    ]
    return local, denied


def _rank_key(
    capability: Capability,
    requirements: tuple[CapabilityRequirement, ...],
    policy: CapabilitySelectionPolicy,
) -> tuple[int, int, int, int, int, int, int, int, str]:
    matching = [item for item in requirements if _matches_requirement(capability, item)]
    operation_coverage = sum(
        len(set(item.operations).intersection(capability.operations))
        for item in matching
    )
    exact_provider = int(any(
        capability.provider in item.required_providers for item in matching
    ))
    requirement_preference = int(any(
        capability.provider in item.preferred_providers for item in matching
    ))
    freshness_fit = int(any(
        item.freshness_required
        and capability.freshness_profile in {"realtime", "near_realtime"}
        for item in matching
    ))
    policy_preference = int(capability.provider in policy.preferred_providers)
    priority = -(
        capability.provider_priority
        if capability.provider_priority is not None
        else 10_000
    )
    return (
        len(matching),
        exact_provider,
        operation_coverage,
        freshness_fit,
        requirement_preference,
        policy_preference,
        _TRUST_ORDER[capability.trust_level],
        priority,
        capability.capability_id,
    )


def _clamp(
    ranked: list[Capability],
    policy: CapabilitySelectionPolicy,
) -> list[Capability]:
    selected: list[Capability] = []
    providers: set[str] = set()
    for capability in ranked:
        if (
            capability.provider not in providers
            and len(providers) >= policy.max_providers_per_action
        ):
            continue
        selected.append(capability)
        providers.add(capability.provider)
        if len(selected) >= policy.max_capabilities_per_action:
            break
    return selected


def _metadata_requires_review(
    capability: Capability,
    policy: CapabilitySelectionPolicy,
) -> bool:
    if not policy.require_reviewed_metadata_for_high_risk:
        return False
    high_risk = (
        capability.risk_level == "high"
        or capability.data_egress_class == "sensitive"
        or bool(set(capability.operations) & MUTATING_OPERATIONS)
        or any("write" in effect or "delete" in effect for effect in capability.side_effects)
    )
    return high_risk and capability.metadata_source not in {"system", "human_reviewed"}


def _matches_requirement(
    capability: Capability,
    requirement: CapabilityRequirement,
) -> bool:
    return match_resource_contract(
        requirement.selector,
        requirement.operation_scope,
        requirement.provider_constraint,
        capability.selector,
        capability.operation_scope,
        candidate_provider=capability.provider,
    ).status == "matched"


def _coverage_for_requirements(
    requirements: tuple[CapabilityRequirement, ...],
    selected: list[Capability],
    denied: list[DeniedCapability] | tuple[DeniedCapability, ...],
    request: ExecutionCapabilityRequest,
    registry: list[Capability],
) -> tuple[CapabilityCoverage, ...]:
    denied_ids = {item.capability_id for item in denied}
    coverage: list[CapabilityCoverage] = []
    for requirement in requirements:
        matches = [
            capability
            for capability in selected
            if _matches_requirement(capability, requirement)
        ]
        eligible_but_denied = [
            capability
            for capability in registry
            if capability.capability_id in denied_ids
            and _matches_requirement(capability, requirement)
        ]
        found_operations = {
            operation for capability in matches for operation in capability.operations
        }
        missing = tuple(
            operation
            for operation in requirement.operations
            if operation not in found_operations
        )
        authority_ok = any(
            _TRUST_ORDER[capability.trust_level]
            >= _TRUST_ORDER[requirement.minimum_trust_level]
            for capability in matches
        )
        freshness_ok = (
            not requirement.freshness_required
            or any(
                capability.freshness_profile in {"realtime", "near_realtime"}
                for capability in matches
            )
        )
        bound_locator = str(request.runtime_context.get("resource_locator", ""))
        resource_bound = (
            not requirement.resource_locator
            or requirement.resource_locator == bound_locator
        )
        if not matches:
            status = "denied" if eligible_but_denied else "unavailable"
            rationale = (
                "matching capabilities were denied by action policy"
                if eligible_but_denied
                else "no capability matches the requirement"
            )
        elif missing or not authority_ok or not freshness_ok or not resource_bound:
            status = "partial"
            rationale = "selected capabilities do not meet the complete requirement contract"
        else:
            status = "satisfied"
            rationale = "operations, trust, freshness and resource binding satisfied"
        coverage.append(CapabilityCoverage(
            requirement_id=requirement.requirement_id,
            status=status,
            selected_capability_ids=tuple(item.capability_id for item in matches),
            missing_operations=missing,
            resource_bound=resource_bound,
            authority_satisfied=authority_ok,
            freshness_satisfied=freshness_ok,
            rationale=rationale,
        ))
    return tuple(coverage)


def _escalation_hint(
    request: ExecutionCapabilityRequest,
    selected: list[Capability],
) -> EscalationHint | None:
    if selected:
        return None
    freshness_requirements = [
        item for item in request.requirements if item.freshness_required
    ]
    if freshness_requirements:
        return EscalationHint(
            reason="freshness_needed",
            requested_domains=tuple(dict.fromkeys(
                domain for item in freshness_requirements for domain in item.semantic_domains
            )),
            requested_operations=tuple(dict.fromkeys(
                operation for item in freshness_requirements for operation in item.operations
            )),
            suggested_execution_shape=request.execution_intent,
        )
    return EscalationHint(
        reason="capability_missing",
        requested_domains=tuple(dict.fromkeys(
            domain for item in request.requirements for domain in item.semantic_domains
        )),
        requested_operations=tuple(request.allowed_operations),
        suggested_execution_shape=request.execution_intent,
    )


def _deny(capability: Capability, reason: str) -> DeniedCapability:
    local_name = _capability_local_name(capability)
    return DeniedCapability(
        capability_id=capability.capability_id,
        local_name=local_name,
        provider=capability.provider,
        reason=reason,
    )


def _capability_local_name(capability: Capability) -> str:
    return str(capability.local_name or capability.capability_id)


def _is_local_capability(capability: Capability) -> bool:
    if capability.provider in {
        "internal", "local", "graphiti", "ms_graphrag", "workspace",
        "structural", "episodic", "reflection",
    }:
        return True
    return not {"external_network", "send_external"} & set(capability.side_effects)


def _context_str(request: ExecutionCapabilityRequest, key: str) -> str | None:
    value = request.runtime_context.get(key)
    return str(value) if value is not None and str(value) else None


def _discovery_snapshot_ref(capabilities: tuple[Capability, ...]) -> str:
    payload = "|".join(
        f"{item.capability_id}:{item.definition_revision}:{item.lifecycle}"
        for item in sorted(capabilities, key=lambda value: value.capability_id)
    )
    return "discovery:" + sha256(payload.encode("utf-8")).hexdigest()[:16]


def _grant_for(request: ExecutionCapabilityRequest, capability: Capability):
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
    availability_revision = int(request.runtime_context.get("availability_revision", 1))
    valid_until = datetime.now(UTC) + timedelta(minutes=10)
    dependencies = GrantDependencySet(
        task_revision=request.task_revision,
        goal_definition_fingerprint=sha256(request.goal_id.encode()).hexdigest()[:16],
        action_fingerprint=sha256(
            f"{request.action_id}:{request.execution_intent}".encode()
        ).hexdigest()[:16],
        capability_definition_revision=capability.definition_revision,
        provider_binding_revision=int(request.runtime_context.get("provider_binding_revision", 1)),
        availability_dependencies=(AvailabilityDependency(
            capability_ref=capability.capability_id,
            availability_revision=availability_revision,
            valid_until=valid_until,
        ),),
        authority_revision=int(request.runtime_context.get("authority_revision", 1)),
        policy_bundle_hash=sha256(request.policy_profile_ref.encode()).hexdigest()[:16],
    )
    common = dict(
        request_id=str(request.request_id),
        action_ref=request.action_id,
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
            agent_binding_ref=f"{capability.provider}:{_capability_local_name(capability)}",
            bounded_sub_goal=str(request.runtime_context.get("bounded_sub_goal", request.execution_intent)),
            context_projection_refs=tuple(request.runtime_context.get("context_projection_refs", ())),
            token_budget=int(request.runtime_context.get("token_budget", 4096)),
            cost_budget=float(request.runtime_context.get("cost_budget", 1.0)),
            time_budget_seconds=int(request.runtime_context.get("time_budget_seconds", 120)),
            max_delegation_depth=int(request.runtime_context.get("max_delegation_depth", 0)),
            completion_contract=str(request.runtime_context.get("completion_contract", "AgentArtifact")),
        )
    return AtomicCapabilityGrant(
        **common,
        capability_ref=capability.capability_id,
        provider_binding_ref=f"{capability.provider}:{_capability_local_name(capability)}",
    )


__all__ = ["CapabilityResolver", "default_capability_policy"]
