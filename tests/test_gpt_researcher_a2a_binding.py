from __future__ import annotations

from personal_agent.kernel.contracts.agent import AgentGovernance, SubagentProfile
from personal_agent.capabilities.contracts.execution import (
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
from personal_agent.tools.mcp_capability import build_capability_portfolio


def test_explicit_gpt_researcher_is_required_delegate_binding():
    decision = TaskAnalysis(
        user_goal="委托 GPT Researcher 调研 A2A",
        goals=[Goal(
            goal_id="goal_1",
            result_contract="artifact",
            description="调研 A2A 协议采用情况",
            success_criteria=[SuccessCriterionDraft(
                description="产出 A2A 协议采用情况报告",
                origin="model_inferred",
            )],
            resource_hints=[ResourceHint(
                semantic_domain="external_research",
                resource_types=["agent"],
                operations=["delegate"],
                user_required_provider="gpt_researcher",
                origin="user_explicit",
                freshness_required=True,
            )],
        )],
    )
    goal = decision.goals[0]
    assert goal.result_contract == "artifact"
    hint = goal.resource_hints[0]
    assert hint.user_required_provider == "gpt_researcher"
    assert hint.origin == "user_explicit"
    assert hint.operations == ["delegate"]

    interpretation = GoalGraphCompiler().compile(decision, decision.user_goal)
    assert interpretation.task_contract.goal_graph.goals[0].result_contract == "artifact"
    requirement = interpretation.task_contract.resource_requirements[0]
    assert requirement.required_providers == ("gpt_researcher",)


def test_generic_research_is_open_but_research_procedure_is_eligible():
    decision = TaskAnalysis(
        user_goal="调研 Agent 工具调用发展",
        goals=[Goal(
            goal_id="goal_1",
            result_contract="artifact",
            description="调研最近一个月 Agent 工具调用的发展",
            success_criteria=[SuccessCriterionDraft(
                description="报告覆盖最近一个月的发展",
                origin="model_inferred",
            )],
            resource_hints=[ResourceHint(
                semantic_domain="external_research",
                resource_types=["research", "report"],
                operations=["search", "read", "verify"],
                freshness_required=True,
            )],
        )],
    )
    assert decision.goals[0].result_contract == "artifact"
    interpretation = GoalGraphCompiler().compile(decision, decision.user_goal)
    assert interpretation.task_contract.goal_graph.goals[0].result_contract == "artifact"
    from personal_agent.runtime.procedure_runtime import (
        PROCEDURE_CATALOG,
        ProcedureApplicabilityResolver,
    )

    candidates = ProcedureApplicabilityResolver(PROCEDURE_CATALOG).resolve(
        interpretation.task_contract,
        interpretation.runtime,
    )
    research = next(item for item in candidates if item.procedure_id == "research_run")
    assert research.status == "eligible"


def test_delegate_requirement_resolves_explicit_fresh_agent_capability():
    profile = SubagentProfile(
        agent_id="gpt_researcher",
        provider="gpt_researcher",
        protocol="a2a_jsonrpc",
        semantic_domains=("external_research",),
        governance=AgentGovernance(side_effects=("external_network",)),
    )
    requirement = CapabilityRequirement.from_dimensions(
        requirement_id="delegate-research",
        purpose="delegate research",
        semantic_domains=("external_research",),
        resource_types=("agent",),
        operations=("delegate",),
        freshness_required=True,
        required_providers=("gpt_researcher",),
        side_effect_class="external_network",
    )
    resolution = CapabilityResolver(build_capability_portfolio(agents=(profile,))).resolve(
        ExecutionCapabilityRequest(
            task_id="task",
            goal_id="goal",
            action_id="delegate-research",
            execution_intent="delegate",
            allowed_kinds=("agent",),
            allowed_operations=("delegate",),
            requirements=(requirement,),
            runtime_context=CapabilityRuntimeContext(
                equivalence_class=CapabilityEquivalenceClass(
                    required_output_contract="AgentArtifact",
                    allowed_side_effect_class="external_network",
                    authority_scope="agent:invoke",
                    trust_floor="external",
                    freshness_contract="fresh",
                    evidence_contract="provider_output",
                    data_egress_class="content",
                    failure_semantics="return_typed_failure",
                ),
            ),
        )
    )
    assert resolution.selected_definition.local_name == "gpt_researcher"
    assert resolution.coverage[0].status == "satisfied"
