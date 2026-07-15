from __future__ import annotations

import json
from pathlib import Path

from evals.resolver_quality.dataset import load_cases
from evals.resolver_quality.scorer import ResolverQualityRun, score_all
from personal_agent.kernel.contracts.capability import (
    CapabilityRequirement,
    CapabilityResolutionRequest,
    CapabilitySelectionPolicy,
    MCPCapability,
)
from personal_agent.planning.capability_resolver import (
    CapabilityResolver,
)
from personal_agent.tools.mcp_capability import CapabilityRegistry


def test_capability_resolver_quality_gate():
    cases = load_cases()
    resolver = CapabilityResolver(_quality_registry())
    runs: list[ResolverQualityRun] = []
    for case in cases:
        resolution = resolver.resolve(CapabilityResolutionRequest(
            task_id="resolver-quality",
            goal_id=case.id,
            action_id=f"{case.id}:resolve",
            meta_capability="acquire",
            allowed_kinds=("mcp_tool",),
            allowed_operations=("search", "read"),
            requirements=tuple(
                CapabilityRequirement.model_validate(item)
                for item in case.requirements
            ),
            policy=CapabilitySelectionPolicy(
                read_only=True,
                max_capabilities_per_action=4,
                max_providers_per_action=2,
            ),
        ))
        runs.append(ResolverQualityRun(
            case_id=case.id,
            selected_capability_ids=tuple(
                capability.capability_id
                for capability in resolution.selected_capabilities
            ),
            denied_reasons=tuple(
                denied.reason
                for denied in resolution.denied_capabilities
            ),
        ))

    report = score_all(cases, tuple(runs))
    baseline = json.loads(Path(__file__).with_name("baseline.json").read_text(encoding="utf-8"))
    failures = report.check_thresholds(baseline)
    assert not failures, "\n".join(failures)


def _quality_registry() -> CapabilityRegistry:
    # The eval exercises the generic registry contract. MCP remains one
    # capability source, not a resolver-specific boundary.
    return CapabilityRegistry(tuple(
        capability.model_copy(update={"metadata_source": "human_reviewed"})
        for capability in (
        MCPCapability(
            capability_id="mcp:github:search_code",
            provider="github",
            server_id="github",
            remote_tool_name="search_code",
            local_name="github.search_code",
            semantic_domains=("codebase",),
            resource_types=("repository", "file", "code"),
            operations=("search",),
            side_effects=("external_network",),
            auth_scope="github:repo:read",
            trust_level="scoped",
            credential_mode="user_token",
            data_egress_class="content",
            attestation_status="verified",
            freshness_profile="realtime",
            provider_priority=1,
        ),
        MCPCapability(
            capability_id="mcp:github:get_file_contents",
            provider="github",
            server_id="github",
            remote_tool_name="get_file_contents",
            local_name="github.get_file_contents",
            semantic_domains=("codebase", "docs"),
            resource_types=("repository", "file"),
            operations=("read",),
            side_effects=("external_network",),
            auth_scope="github:repo:read",
            trust_level="scoped",
            credential_mode="user_token",
            data_egress_class="content",
            attestation_status="verified",
            freshness_profile="realtime",
            provider_priority=1,
        ),
        MCPCapability(
            capability_id="mcp:github:search_repositories",
            provider="github",
            server_id="github",
            remote_tool_name="search_repositories",
            local_name="github.search_repositories",
            semantic_domains=("codebase", "repository_discovery"),
            resource_types=("repository",),
            operations=("search",),
            side_effects=("external_network",),
            auth_scope="github:repo:read",
            trust_level="scoped",
            credential_mode="user_token",
            data_egress_class="metadata",
            attestation_status="verified",
            freshness_profile="realtime",
            provider_priority=2,
        ),
        MCPCapability(
            capability_id="mcp:notion:post-search",
            provider="notion",
            server_id="notion",
            remote_tool_name="post-search",
            local_name="notion.search",
            semantic_domains=("workspace_knowledge", "docs"),
            resource_types=("page", "data_source"),
            operations=("search",),
            side_effects=("external_network",),
            auth_scope="notion:workspace:read",
            trust_level="scoped",
            credential_mode="user_token",
            data_egress_class="content",
            attestation_status="verified",
            freshness_profile="realtime",
            provider_priority=1,
        ),
        MCPCapability(
            capability_id="mcp:notion:retrieve-page-markdown",
            provider="notion",
            server_id="notion",
            remote_tool_name="retrieve-page-markdown",
            local_name="notion.retrieve_page_markdown",
            semantic_domains=("workspace_knowledge", "docs"),
            resource_types=("page",),
            operations=("read",),
            side_effects=("external_network",),
            auth_scope="notion:workspace:read",
            trust_level="scoped",
            credential_mode="user_token",
            data_egress_class="content",
            attestation_status="verified",
            freshness_profile="realtime",
            provider_priority=1,
        ),
    )))
