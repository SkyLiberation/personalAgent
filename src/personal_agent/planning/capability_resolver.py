from __future__ import annotations

from personal_agent.kernel.contracts.capability import (
    Capability,
    CapabilityCoverage,
    CapabilityRequirement,
    CapabilityResolutionDecision,
    CapabilityResolutionRequest,
    ResolutionConstraints,
    CapabilitySelectionPolicy,
    DeniedCapability,
    EscalationHint,
)
from personal_agent.kernel.contracts.policy import PolicyEvaluator, PolicyInput
from personal_agent.planning.capability_validation import ResolutionValidator
from personal_agent.planning.outcome_ranking import (
    CapabilityRanker,
    OutcomeAwareCapabilityRanker,
)
from personal_agent.tools.mcp_capability import CapabilityRegistry
from personal_agent.kernel.contracts.resource import MUTATING_OPERATIONS, match_resource_contract
_TRUST_ORDER = {"untrusted": 0, "external": 1, "scoped": 2, "trusted": 3}


class CapabilityResolver:
    """Resolve structured action requirements against governed capabilities."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        policy_engine: PolicyEvaluator | None = None,
        validator: ResolutionValidator | None = None,
        ranker: CapabilityRanker | None = None,
    ) -> None:
        self._registry = registry
        self._policy_engine = policy_engine
        self._validator = validator or ResolutionValidator()
        self._ranker = ranker or OutcomeAwareCapabilityRanker()

    def resolve(self, request: CapabilityResolutionRequest) -> CapabilityResolutionDecision:
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
        selected = _clamp(ranked, request.policy)
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
        resolution = CapabilityResolutionDecision(
            request_scope_id=request.scope_id,
            selected_capabilities=tuple(selected),
            denied_capabilities=tuple(denied),
            allowed_tools=tuple(
                _capability_local_name(capability)
                for capability in selected
                if capability.kind in {"local_tool", "mcp_tool"}
            ),
            selected_retrievers=tuple(
                _capability_local_name(capability)
                for capability in selected
                if capability.kind == "retriever"
            ),
            allowed_agents=tuple(
                _capability_local_name(capability)
                for capability in selected
                if capability.kind == "agent"
            ),
            coverage=coverage,
            constraints=ResolutionConstraints(
                task_id=request.task_id,
                goal_id=request.goal_id,
                action_id=request.action_id,
                meta_capability=request.meta_capability,
                allowed_kinds=request.allowed_kinds,
                allowed_operations=request.allowed_operations,
                hard_denied_capability_ids=tuple(sorted(hard_denied_ids)),
                ranking=ranking_audit,
            ),
            escalation_hint=_escalation_hint(request, selected),
            rationale=(
                "selected " + ", ".join(item.capability_id for item in selected)
                if selected
                else "no capability satisfies the current action contract"
            ),
            confidence=0.85 if selected else 0.4,
        )

        errors = self._validator.errors(
            request,
            resolution,
            hard_denied_ids=frozenset(hard_denied_ids),
        )
        if errors:
            selected_denials = tuple(
                _deny(capability, "resolution_validator:" + ",".join(errors))
                for capability in resolution.selected_capabilities
            )
            return resolution.model_copy(update={
                "validation_state": "rejected",
                "selected_capabilities": (),
                "allowed_tools": (),
                "selected_retrievers": (),
                "allowed_agents": (),
                "coverage": _coverage_for_requirements(
                    request.requirements,
                    [],
                    [*resolution.denied_capabilities, *selected_denials],
                    request,
                    self._registry.list(),
                ),
                "denied_capabilities": (*resolution.denied_capabilities, *selected_denials),
                "constraints": resolution.constraints.model_copy(update={
                    "validator_errors": errors,
                }),
                "rationale": "resolution rejected by invariant validator",
                "confidence": 0.0,
            })
        return resolution

    def _ineligibility_reason(
        self,
        capability: Capability,
        request: CapabilityResolutionRequest,
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
        request: CapabilityResolutionRequest,
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
    meta_capability: str,
    *,
    mutating: bool = False,
) -> CapabilitySelectionPolicy:
    if mutating or meta_capability in {"commit", "remember"}:
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
    request: CapabilityResolutionRequest,
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
    request: CapabilityResolutionRequest,
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
    request: CapabilityResolutionRequest,
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
            suggested_execution_shape=request.meta_capability,
        )
    return EscalationHint(
        reason="capability_missing",
        requested_domains=tuple(dict.fromkeys(
            domain for item in request.requirements for domain in item.semantic_domains
        )),
        requested_operations=tuple(request.allowed_operations),
        suggested_execution_shape=request.meta_capability,
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


def _context_str(request: CapabilityResolutionRequest, key: str) -> str | None:
    value = request.runtime_context.get(key)
    return str(value) if value is not None and str(value) else None


__all__ = ["CapabilityResolver", "default_capability_policy"]
