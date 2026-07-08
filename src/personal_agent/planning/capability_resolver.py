from __future__ import annotations

import re

from personal_agent.kernel.contracts.capability import (
    CapabilityOperation,
    CapabilityResolution,
    CapabilityResolutionRequest,
    CapabilitySelectionPolicy,
    DeniedCapability,
    MCPCapability,
)
from personal_agent.tools.mcp_capability import MCPCapabilityRegistry


_SCOPE_DOMAINS: dict[str, tuple[str, ...]] = {
    "external_codebase_qa": ("codebase", "docs", "repository_discovery"),
    "external_workspace_qa": ("workspace_knowledge", "docs"),
    "external_project_ops": ("project_management", "codebase", "workspace_knowledge", "docs"),
}

_WRITE_MARKERS = (
    "创建", "新建", "更新", "修改", "删除", "移动", "评论", "写入", "发布",
    "create", "update", "delete", "move", "comment", "write", "publish",
)

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

    def __init__(self, registry: MCPCapabilityRegistry) -> None:
        self._registry = registry

    def resolve(self, request: CapabilityResolutionRequest) -> CapabilityResolution:
        text = request.task_text.strip()
        lowered = text.lower()
        denied: list[DeniedCapability] = []

        if request.policy.local_first and _looks_local_first(text, lowered):
            return CapabilityResolution(
                request=request,
                denied_capabilities=tuple(
                    _deny(capability, "local_first")
                    for capability in self._registry.list()
                    if _in_scope(capability, request.workflow_scope)
                ),
                rationale="local-first request; external MCP capabilities denied",
                confidence=0.95,
            )

        if request.policy.read_only and _has_any(text, lowered, _WRITE_MARKERS):
            return CapabilityResolution(
                request=request,
                denied_capabilities=tuple(
                    _deny(capability, "read_only_policy")
                    for capability in self._registry.list()
                    if _in_scope(capability, request.workflow_scope)
                ),
                rationale="read-only workflow denied write-like request",
                confidence=0.9,
            )

        candidates: list[MCPCapability] = []
        allowed_ops = set(request.allowed_operations)
        for capability in self._registry.list():
            if not _in_scope(capability, request.workflow_scope):
                continue
            if not set(capability.operations) & allowed_ops:
                denied.append(_deny(capability, "operation_not_allowed"))
                continue
            if request.policy.deny_sensitive_egress and capability.data_egress_class == "sensitive":
                denied.append(_deny(capability, "sensitive_egress_denied"))
                continue
            if (
                request.policy.require_trusted_for_sensitive
                and capability.data_egress_class == "sensitive"
                and capability.trust_level not in {"trusted", "scoped"}
            ):
                denied.append(_deny(capability, "sensitive_requires_trusted_provider"))
                continue
            candidates.append(capability)

        ranked = sorted(
            candidates,
            key=lambda capability: _rank(capability, text, lowered, request.policy),
            reverse=True,
        )
        ranked = [capability for capability in ranked if _rank(capability, text, lowered, request.policy) > 0]
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
            else "no matching external capability"
        )
        return CapabilityResolution(
            request=request,
            selected_capabilities=tuple(selected),
            denied_capabilities=tuple(denied),
            allowed_tools=tuple(capability.local_tool_name for capability in selected),
            rationale=rationale,
            confidence=0.85 if selected else 0.4,
        )


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
    return CapabilitySelectionPolicy(max_capabilities_per_step=4, max_providers_per_step=2)


def _in_scope(capability: MCPCapability, workflow_scope: str) -> bool:
    domains = set(_SCOPE_DOMAINS.get(workflow_scope, ()))
    return bool(domains & set(capability.semantic_domains))


def _looks_local_first(text: str, lowered: str) -> bool:
    return _has_any(text, lowered, _LOCAL_FIRST_MARKERS)


def _rank(
    capability: MCPCapability,
    text: str,
    lowered: str,
    policy: CapabilitySelectionPolicy,
) -> int:
    score = 0
    for operation, markers in _OPERATION_MARKERS:
        if operation in capability.operations and _has_any(text, lowered, markers):
            score += 4
    for resource, markers in _RESOURCE_MARKERS:
        if resource in capability.resource_types and _has_any(text, lowered, markers):
            score += 3
    for domain in capability.semantic_domains:
        if domain.replace("_", " ") in lowered or domain in lowered:
            score += 2
    if capability.provider.lower() in lowered:
        score += 5
    if capability.provider in policy.preferred_providers:
        score += 2
    if capability.provider_priority is not None:
        score += max(0, 10 - capability.provider_priority)
    if _mentions_repo(text) and "repository" in capability.resource_types:
        score += 2
    if _mentions_page_id(text) and "page" in capability.resource_types and "read" in capability.operations:
        score += 6
    return score


def _clamp(
    ranked: list[MCPCapability],
    policy: CapabilitySelectionPolicy,
) -> list[MCPCapability]:
    selected: list[MCPCapability] = []
    providers: set[str] = set()
    for capability in ranked:
        if capability.provider not in providers and len(providers) >= policy.max_providers_per_step:
            continue
        selected.append(capability)
        providers.add(capability.provider)
        if len(selected) >= policy.max_capabilities_per_step:
            break
    return selected


def _deny(capability: MCPCapability, reason: str) -> DeniedCapability:
    return DeniedCapability(
        capability_id=capability.capability_id,
        local_tool_name=capability.local_tool_name,
        provider=capability.provider,
        reason=reason,
    )


def _has_any(text: str, lowered: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text or marker.lower() in lowered for marker in markers)


def _mentions_repo(text: str) -> bool:
    return bool(re.search(r"(?:github\.com/|repo:)?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text))


def _mentions_page_id(text: str) -> bool:
    return bool(re.search(r"\b(?:[0-9a-fA-F]{32}|[0-9a-fA-F-]{36})\b", text))


__all__ = ["CapabilityResolver", "default_capability_policy_for_scope"]
