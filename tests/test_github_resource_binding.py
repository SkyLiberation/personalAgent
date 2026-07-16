from __future__ import annotations

from personal_agent.capabilities.contracts.execution import (
    Capability,
    CapabilityRequirement,
    ExecutionCapabilityRequest,
)
from personal_agent.capabilities.resolver import CapabilityResolver
from personal_agent.planning.task_compiler import GoalGraphCompiler
from personal_agent.planning.task_analyzer import Goal, ResourceHint, TaskAnalysis
from datetime import UTC, datetime
from personal_agent.capabilities.portfolio import (
    CapabilityPortfolio,
    ExecutionCapabilityAvailability,
)


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

    task = GoalGraphCompiler().compile(decision, decision.user_goal).task_contract
    requirement = task.resource_requirements[0]
    assert requirement.semantic_domain == "codebase"
    assert requirement.required_providers == ("github",)


def test_required_provider_binding_filters_other_codebase_providers():
    github = _repo_capability("github")
    gitlab = _repo_capability("gitlab")
    requirement = CapabilityRequirement.from_dimensions(
        requirement_id="repo-read",
        purpose="read repository",
        semantic_domains=("codebase",),
        resource_types=("repository",),
        operations=("search", "read"),
        required_providers=("github",),
    )
    portfolio = CapabilityPortfolio((gitlab, github))
    for capability in (gitlab, github):
        portfolio.observe(ExecutionCapabilityAvailability(
            capability_ref=capability.capability_id,
            availability_revision=1,
            status="available",
            credential_ready=True,
            health_observed_at=datetime.now(UTC),
            provider_binding_revision=1,
        ))
    resolution = CapabilityResolver(portfolio).resolve(
        ExecutionCapabilityRequest(
            task_id="task",
            goal_id="goal",
            action_id="read-repository",
            execution_intent="acquire",
            allowed_kinds=("mcp_tool",),
            allowed_operations=("search", "read"),
            requirements=(requirement,),
        )
    )
    assert resolution.selected_definition.provider == "github"
    assert resolution.coverage[0].status == "satisfied"


def _repo_capability(provider: str) -> Capability:
    return Capability.from_dimensions(
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
