from __future__ import annotations

from personal_agent.kernel.contracts.capability import (
    Capability,
    CapabilityRequirement,
    CapabilityResolutionRequest,
)
from personal_agent.planning.capability_resolver import CapabilityResolver
from personal_agent.planning.goal_graph import GoalGraphCompiler
from personal_agent.planning.task_analyzer import Goal, ResourceHint, TaskAnalysis
from personal_agent.tools.mcp_capability import CapabilityRegistry


def test_github_question_becomes_provider_neutral_goal_with_required_binding():
    decision = TaskAnalysis(
        user_goal="查找 search_code 实现",
        goals=[Goal(
            goal_id="goal_1",
            result_contract="response",
            description="查找 search_code 实现",
            resource_hints=[ResourceHint(
                semantic_domain="codebase",
                resource_types=["repository", "code"],
                operations=["search", "read"],
                locator="github/github-mcp-server",
                user_required_provider="github",
                origin="user_explicit",
            )],
        )],
    )

    goal = decision.goals[0]
    assert goal.result_contract == "response"
    assert goal.resource_hints[0].user_required_provider == "github"
    assert goal.resource_hints[0].origin == "user_explicit"

    task = GoalGraphCompiler().compile(decision, decision.user_goal).task_spec
    requirement = task.resource_requirements[0]
    assert requirement.semantic_domain == "codebase"
    assert requirement.required_providers == ("github",)


def test_required_provider_binding_filters_other_codebase_providers():
    github = _repo_capability("github")
    gitlab = _repo_capability("gitlab")
    requirement = CapabilityRequirement(
        requirement_id="repo-read",
        purpose="read repository",
        semantic_domains=("codebase",),
        resource_types=("repository",),
        operations=("search", "read"),
        required_providers=("github",),
    )
    resolution = CapabilityResolver(CapabilityRegistry((gitlab, github))).resolve(
        CapabilityResolutionRequest(
            task_id="task",
            goal_id="goal",
            action_id="read-repository",
            meta_capability="acquire",
            allowed_kinds=("mcp_tool",),
            allowed_operations=("search", "read"),
            requirements=(requirement,),
        )
    )
    assert [item.provider for item in resolution.selected_capabilities] == ["github"]
    assert resolution.coverage[0].status == "satisfied"


def _repo_capability(provider: str) -> Capability:
    return Capability(
        capability_id=f"mcp:{provider}:repository",
        kind="mcp_tool",
        provider=provider,
        local_name=f"{provider}.repository",
        semantic_domains=("codebase",),
        resource_types=("repository", "code"),
        operations=("search", "read"),
        trust_level="scoped",
        metadata_source="human_reviewed",
    )
