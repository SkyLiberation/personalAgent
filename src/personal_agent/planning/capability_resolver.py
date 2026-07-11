from __future__ import annotations

import re

from personal_agent.kernel.contracts.capability import (
    Capability,
    CapabilityCoverage,
    CapabilityKind,
    CapabilityOperation,
    CapabilityRequirement,
    CapabilityResolution,
    CapabilityResolutionRequest,
    CapabilitySelectionPolicy,
    DeniedCapability,
    EscalationHint,
)
from personal_agent.kernel.contracts.policy import PolicyEvaluator, PolicyInput
from personal_agent.planning.capability_validation import ResolutionValidator
from personal_agent.tools.mcp_capability import CapabilityRegistry


_SCOPE_DOMAINS: dict[str, tuple[str, ...]] = {
    "ask": ("local_memory", "graph", "workspace_knowledge", "web", "docs", "codebase"),
    "capture_text": ("capture", "knowledge_lifecycle"),
    "capture_link": ("capture", "web"),
    "capture_file": ("capture", "artifact"),
    "solidify_conversation": ("conversation", "knowledge_lifecycle"),
    "external_codebase_qa": ("codebase", "docs", "repository_discovery"),
    "external_workspace_qa": ("workspace_knowledge", "docs"),
    "external_project_ops": ("project_management", "codebase", "workspace_knowledge", "docs"),
}

_WRITE_MARKERS = (
    "创建", "新建", "更新", "修改", "删除", "移动", "评论", "写入", "发布",
    "create", "update", "delete", "move", "comment", "write", "publish",
)

_KIND_OUTPUTS: dict[CapabilityKind, str] = {
    "local_tool": "allowed_tools",
    "mcp_tool": "allowed_tools",
    "retriever": "selected_retrievers",
    "agent": "allowed_agents",
    "workflow_action": "workflow_actions",
}

_LOCAL_FIRST_MARKERS = (
    "我的笔记", "个人知识库", "之前的笔记", "本地知识", "我之前", "记忆里",
    "my notes", "personal knowledge", "local memory",
)

_OPERATION_MARKERS: tuple[tuple[CapabilityOperation, tuple[str, ...]], ...] = (
    ("read", ("读取", "打开", "read", "fetch", "file", "README", "页面", "page", "markdown")),
    ("search", ("搜索", "查找", "查询", "在哪", "在哪里", "实现", "search", "find", "repo:", "topic:", "language:")),
    ("list", ("列出", "列表", "list")),
    ("create", ("创建", "新建", "create")),
    ("update", ("更新", "修改", "update")),
    ("delete", ("删除", "delete")),
)

_RESOURCE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("file", ("readme", ".md", ".py", ".ts", ".tsx", ".js", ".go", ".rs", "文件", "代码")),
    ("repository", ("github", "repo:", "repository", "仓库", "stars:", "topic:", "language:")),
    ("code", ("代码", "实现", "函数", "class", "search_code")),
    ("page", ("notion", "页面", "page", "markdown")),
    ("data_source", ("notion", "database", "data source", "wiki", "知识库")),
    ("issue", ("issue", "ticket", "任务", "缺陷", "jira", "linear")),
)


class CapabilityResolver:
    """Select auditable external capabilities for a workflow step.

    The resolver is intentionally deterministic in P2/P3: filter by workflow
    scope and policy first, then apply a transparent text/rule ranker. A future
    semantic ranker can replace ``_rank`` without changing workflow contracts.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        policy_engine: PolicyEvaluator | None = None,
        validator: ResolutionValidator | None = None,
    ) -> None:
        self._registry = registry
        self._policy_engine = policy_engine
        self._validator = validator or ResolutionValidator()

    def resolve(self, request: CapabilityResolutionRequest) -> CapabilityResolution:
        text = request.task_text.strip()
        lowered = text.lower()
        denied: list[DeniedCapability] = []
        scope = request.scope
        allowed_kinds = set(request.allowed_kinds)
        if request.policy.read_only and _has_any(text, lowered, _WRITE_MARKERS):
            return CapabilityResolution(
                request=request,
                denied_capabilities=tuple(
                    _deny(capability, "read_only_policy")
                    for capability in self._registry.list()
                    if capability.kind in allowed_kinds and _in_scope(capability, scope)
                ),
                rationale="read-only workflow denied write-like request",
                confidence=0.9,
            ).transition("resolved", reason="read_only_request").transition(
                "policy_clamped", reason="read_only_policy"
            )
        candidates: list[Capability] = []
        hard_denied_ids: set[str] = set()
        allowed_ops = set(request.allowed_operations)
        expected_names = {
            str(item)
            for item in request.runtime_context.get("expected_local_names", ())
            if str(item)
        }
        for capability in self._registry.list():
            if not capability.selectable:
                denied.append(_deny(capability, "internal_workflow_action"))
                continue
            if capability.selectable_only_in_steps and request.step_id not in capability.selectable_only_in_steps:
                denied.append(_deny(capability, "not_selectable_in_step"))
                continue
            if capability.kind not in allowed_kinds:
                denied.append(_deny(capability, "kind_not_allowed"))
                continue
            if not _in_scope(capability, scope):
                continue
            if request.requirements and not any(
                _matches_requirement(capability, requirement)
                for requirement in request.requirements
            ):
                denied.append(_deny(capability, "requirement_mismatch"))
                continue
            if expected_names and _capability_local_name(capability) not in expected_names:
                denied.append(_deny(capability, "not_expected_for_step"))
                continue
            if not set(capability.operations).issubset(allowed_ops):
                denied.append(_deny(capability, "operation_not_allowed"))
                continue
            if _metadata_requires_review(capability, request.policy):
                denied.append(_deny(capability, "unreviewed_high_risk_metadata"))
                hard_denied_ids.add(capability.capability_id)
                continue
            if request.policy.deny_sensitive_egress and capability.data_egress_class == "sensitive":
                denied.append(_deny(capability, "sensitive_egress_denied"))
                hard_denied_ids.add(capability.capability_id)
                continue
            if (
                request.policy.require_trusted_for_sensitive
                and capability.data_egress_class == "sensitive"
                and capability.trust_level not in {"trusted", "scoped"}
            ):
                denied.append(_deny(capability, "sensitive_requires_trusted_provider"))
                hard_denied_ids.add(capability.capability_id)
                continue
            policy_decision = self._policy_decision(capability, request)
            if policy_decision is not None and policy_decision.effect in {"deny", "require_escalation"}:
                denied.append(_deny(capability, f"policy:{policy_decision.rule}"))
                hard_denied_ids.add(capability.capability_id)
                continue
            candidates.append(capability)

        if request.policy.local_first and _looks_local_first(text, lowered):
            local_candidates = [capability for capability in candidates if _is_local_capability(capability)]
            local_ids = {capability.capability_id for capability in local_candidates}
            denied.extend(
                _deny(capability, "local_first")
                for capability in candidates
                if capability.capability_id not in local_ids
            )
            candidates = local_candidates

        ranked = sorted(
            candidates,
            key=lambda capability: _rank_key(capability, text, lowered, request.policy, request.requirements),
            reverse=True,
        )
        selected = _clamp(ranked, request.policy)
        selected_ids = {capability.capability_id for capability in selected}
        denied.extend(
            _deny(capability, "policy_clamped")
            for capability in ranked
            if capability.capability_id not in selected_ids
        )
        rationale = (
            "selected " + ", ".join(capability.capability_id for capability in selected)
            if selected
            else "no matching capability in current step scope"
        )
        coverage = _coverage_for_requirements(request.requirements, selected, request)
        resolution = CapabilityResolution(
            request=request,
            selected_capabilities=tuple(selected),
            denied_capabilities=tuple(denied),
            allowed_tools=tuple(_capability_local_name(capability) for capability in selected if capability.kind in {"local_tool", "mcp_tool"}),
            selected_retrievers=tuple(_capability_local_name(capability) for capability in selected if capability.kind == "retriever"),
            allowed_agents=tuple(_capability_local_name(capability) for capability in selected if capability.kind == "agent"),
            workflow_actions=tuple(_capability_local_name(capability) for capability in selected if capability.kind == "workflow_action"),
            coverage=coverage,
            constraints={
                "workflow_id": scope,
                "step_id": request.step_id,
                "step_action_type": request.step_action_type,
                "allowed_kinds": list(request.allowed_kinds),
                "allowed_operations": list(request.allowed_operations),
                "hard_denied_capability_ids": sorted(hard_denied_ids),
                "coverage": [item.model_dump(mode="json") for item in coverage],
            },
            escalation_hint=_escalation_hint(request, selected),
            rationale=rationale,
            confidence=0.85 if selected else 0.4,
        ).transition("resolved", reason="deterministic_filter_and_rank")
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
                "selected_capabilities": (),
                "allowed_tools": (),
                "selected_retrievers": (),
                "allowed_agents": (),
                "workflow_actions": (),
                "coverage": _coverage_for_requirements(request.requirements, [], request),
                "denied_capabilities": (*resolution.denied_capabilities, *selected_denials),
                "constraints": {**resolution.constraints, "validator_errors": list(errors)},
                "rationale": "resolution rejected by invariant validator",
                "confidence": 0.0,
            }).transition("rejected", reason=";".join(errors))
        return resolution.transition("validated", reason="resolution_invariants_valid").transition(
            "policy_clamped", reason="policy_prefilter_and_clamp_applied"
        )

    def _policy_decision(self, capability: Capability, request: CapabilityResolutionRequest):
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
            # This is an authorization prefilter, before an allowlist exists.
            # ToolGateway later evaluates the concrete invocation as `react`
            # with the resolved allowlist attached.
            execution_mode="capability_resolution",
            tool_name=_capability_local_name(capability),
            risk_level=capability.risk_level,  # type: ignore[arg-type]
            side_effects=capability.side_effects,  # type: ignore[arg-type]
            permission_scope=capability.auth_scope,
            react_allowed_tools=frozenset(request.runtime_context.get("react_allowed_tools", ())),
        ))


def default_capability_policy_for_scope(scope: str) -> CapabilitySelectionPolicy:
    if scope == "external_codebase_qa":
        return CapabilitySelectionPolicy(
            preferred_providers=("github",),
            max_capabilities_per_step=3,
            max_providers_per_step=1,
        )
    if scope == "external_workspace_qa":
        return CapabilitySelectionPolicy(
            preferred_providers=("notion",),
            max_capabilities_per_step=2,
            max_providers_per_step=1,
        )
    if scope in {"capture_text", "capture_link", "capture_file", "solidify_conversation"}:
        return CapabilitySelectionPolicy(
            local_first=False,
            read_only=False,
            preferred_providers=("internal",),
            max_capabilities_per_step=2,
            max_providers_per_step=1,
        )
    if scope in {
        "delete_knowledge",
        "maintain_knowledge",
        "consolidate_knowledge",
        "research_once",
        "execute_research_run",
        "manage_research",
    }:
        return CapabilitySelectionPolicy(
            local_first=False,
            read_only=False,
            preferred_providers=("internal",),
            max_capabilities_per_step=2,
            max_providers_per_step=1,
        )
    if scope == "gpt_researcher_a2a":
        return CapabilitySelectionPolicy(
            local_first=False,
            read_only=True,
            preferred_providers=("gpt_researcher",),
            max_capabilities_per_step=1,
            max_providers_per_step=1,
        )
    return CapabilitySelectionPolicy(max_capabilities_per_step=4, max_providers_per_step=2)


def _in_scope(capability: Capability, workflow_scope: str) -> bool:
    domains = set(_SCOPE_DOMAINS.get(workflow_scope, ()))
    if not domains:
        return True
    return bool(domains & set(capability.semantic_domains))


def _looks_local_first(text: str, lowered: str) -> bool:
    return _has_any(text, lowered, _LOCAL_FIRST_MARKERS)


def _rank_key(
    capability: Capability,
    text: str,
    lowered: str,
    policy: CapabilitySelectionPolicy,
    requirements: tuple[CapabilityRequirement, ...] = (),
) -> tuple[int, int, int, int, int, int, int, int, str]:
    """Lexicographic ranking after hard eligibility filters.

    Different concerns intentionally remain separate instead of being collapsed
    into a hand-tuned weighted score.
    """
    requirement_fit = int(any(_matches_requirement(capability, item) for item in requirements))
    operation_fit = sum(
        1 for operation, markers in _OPERATION_MARKERS
        if operation in capability.operations and _has_any(text, lowered, markers)
    )
    resource_fit = sum(
        1 for resource, markers in _RESOURCE_MARKERS
        if resource in capability.resource_types and _has_any(text, lowered, markers)
    )
    domain_fit = sum(
        1 for domain in capability.semantic_domains
        if domain.replace("_", " ") in lowered or domain in lowered
    )
    explicit_provider = int(capability.provider.lower() in lowered)
    preference = int(capability.provider in policy.preferred_providers)
    priority = -(capability.provider_priority if capability.provider_priority is not None else 10_000)
    return (
        requirement_fit,
        explicit_provider,
        operation_fit,
        resource_fit,
        domain_fit,
        preference,
        int(_is_local_capability(capability)),
        priority,
        capability.capability_id,
    )


def _is_semantically_eligible(
    capability: Capability,
    text: str,
    lowered: str,
    requirements: tuple[CapabilityRequirement, ...],
) -> bool:
    if requirements:
        return any(_matches_requirement(capability, item) for item in requirements)
    return any((
        capability.provider.lower() in lowered,
        any(
            operation in capability.operations and _has_any(text, lowered, markers)
            for operation, markers in _OPERATION_MARKERS
        ),
        any(
            resource in capability.resource_types and _has_any(text, lowered, markers)
            for resource, markers in _RESOURCE_MARKERS
        ),
        any(domain.replace("_", " ") in lowered or domain in lowered for domain in capability.semantic_domains),
    ))


def _clamp(
    ranked: list[Capability],
    policy: CapabilitySelectionPolicy,
) -> list[Capability]:
    selected: list[Capability] = []
    providers: set[str] = set()
    for capability in ranked:
        if capability.provider not in providers and len(providers) >= policy.max_providers_per_step:
            continue
        selected.append(capability)
        providers.add(capability.provider)
        if len(selected) >= policy.max_capabilities_per_step:
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
        or any(operation in {"create", "update", "delete"} for operation in capability.operations)
        or any("write" in effect or "delete" in effect for effect in capability.side_effects)
    )
    return high_risk and capability.metadata_source not in {"system", "human_reviewed"}


def _escalation_hint(
    request: CapabilityResolutionRequest,
    selected: list[Capability],
) -> EscalationHint | None:
    if selected:
        return None
    if bool(request.runtime_context.get("needs_freshness")):
        return EscalationHint(
            reason="freshness_needed",
            requested_domains=("web",),
            requested_operations=("search", "read"),
            suggested_execution_shape="retrieve",
        )
    return EscalationHint(
        reason="capability_missing",
        requested_domains=(),
        requested_operations=tuple(request.allowed_operations),
        suggested_execution_shape=request.step_action_type or None,
    )


def _context_str(request: CapabilityResolutionRequest, key: str) -> str | None:
    value = request.runtime_context.get(key)
    return str(value) if value is not None and str(value) else None


def _deny(capability: Capability, reason: str) -> DeniedCapability:
    local_name = _capability_local_name(capability)
    return DeniedCapability(
        capability_id=capability.capability_id,
        local_name=local_name,
        local_tool_name=local_name,
        provider=capability.provider,
        reason=reason,
    )


def _capability_local_name(capability: Capability) -> str:
    legacy_tool_name = getattr(capability, "local_tool_name", "")
    return str(capability.local_name or legacy_tool_name or capability.capability_id)


def _is_local_capability(capability: Capability) -> bool:
    if capability.kind == "retriever" and capability.provider in {
        "local",
        "graphiti",
        "ms_graphrag",
        "workspace",
        "structural",
        "episodic",
        "reflection",
    }:
        return True
    if capability.provider in {"internal", "local"}:
        return True
    return not {"external_network", "send_external"} & set(capability.side_effects)


def _matches_requirement(capability: Capability, requirement: CapabilityRequirement) -> bool:
    if requirement.semantic_domains and not set(requirement.semantic_domains).intersection(capability.semantic_domains):
        return False
    if requirement.resource_types and not set(requirement.resource_types).intersection(capability.resource_types):
        return False
    return bool(set(requirement.operations).intersection(capability.operations))


def _coverage_for_requirements(
    requirements: tuple[CapabilityRequirement, ...],
    selected: list[Capability],
    request: CapabilityResolutionRequest,
) -> tuple[CapabilityCoverage, ...]:
    coverage: list[CapabilityCoverage] = []
    trust_order = {"untrusted": 0, "external": 1, "scoped": 2, "trusted": 3}
    for requirement in requirements:
        matches = [capability for capability in selected if _matches_requirement(capability, requirement)]
        found_operations = {
            operation for capability in matches for operation in capability.operations
        }
        missing = tuple(operation for operation in requirement.operations if operation not in found_operations)
        authority_ok = any(
            trust_order[capability.trust_level] >= trust_order[requirement.minimum_trust_level]
            for capability in matches
        )
        freshness_ok = (
            not requirement.freshness_required
            or any(capability.freshness_profile in {"realtime", "near_realtime"} for capability in matches)
        )
        bound_locator = str(request.runtime_context.get("resource_locator", ""))
        resource_bound = not requirement.resource_locator or requirement.resource_locator == bound_locator
        if not matches:
            status = "unavailable"
            rationale = "no selected capability matches the requirement"
        elif missing or not authority_ok or not freshness_ok or not resource_bound:
            status = "partial"
            rationale = "selected capabilities do not meet the complete requirement contract"
        else:
            status = "satisfied"
            rationale = "operations, trust, freshness and resource binding satisfied"
        coverage.append(CapabilityCoverage(
            requirement_id=requirement.requirement_id,
            status=status,
            selected_capability_ids=tuple(capability.capability_id for capability in matches),
            missing_operations=missing,
            resource_bound=resource_bound,
            authority_satisfied=authority_ok,
            freshness_satisfied=freshness_ok,
            rationale=rationale,
        ))
    return tuple(coverage)


def _has_any(text: str, lowered: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text or marker.lower() in lowered for marker in markers)


def _mentions_repo(text: str) -> bool:
    return bool(re.search(r"(?:github\.com/|repo:)?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text))


def _mentions_page_id(text: str) -> bool:
    return bool(re.search(r"\b(?:[0-9a-fA-F]{32}|[0-9a-fA-F-]{36})\b", text))


__all__ = ["CapabilityResolver", "default_capability_policy_for_scope"]
