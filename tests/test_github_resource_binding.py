from __future__ import annotations

from personal_agent.capabilities.contracts.execution import (
    Capability,
    CapabilityEquivalenceClass,
    CapabilityRequirement,
    CapabilityRuntimeContext,
    ExecutionCapabilityRequest,
)
from personal_agent.capabilities.resolver import CapabilityResolver
from personal_agent.planning.task_compiler import GoalGraphCompiler
from personal_agent.planning.task_analyzer import (
    Goal,
    ResourceHint,
    SuccessCriterionDraft,
    TaskAnalysis,
)
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
            success_criteria=[SuccessCriterionDraft(
                description="定位 search_code 的实现位置",
                origin="model_inferred",
            )],
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
        output_contract="ToolResult",
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
            runtime_context=CapabilityRuntimeContext(
                equivalence_class=CapabilityEquivalenceClass(
                    required_output_contract="ToolResult",
                    allowed_side_effect_class="none",
                    authority_scope="mcp:tool",
                    trust_floor="external",
                    freshness_contract="static",
                    evidence_contract="provider_output",
                    data_egress_class="content",
                    failure_semantics="return_typed_failure",
                ),
            ),
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
        output_contract="ToolResult",
        auth_scope="mcp:tool",
        trust_level="scoped",
        metadata_source="human_reviewed",
        evidence_contract="provider_output",
        failure_semantics="return_typed_failure",
    )
