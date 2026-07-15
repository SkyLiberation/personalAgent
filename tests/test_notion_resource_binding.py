from __future__ import annotations

from personal_agent.planning.goal_graph import GoalGraphCompiler
from personal_agent.planning.task_analyzer import Goal, ResourceHint, TaskAnalysis


def test_notion_read_becomes_ask_with_workspace_requirement():
    decision = _notion_analysis("response", ["search", "read"])
    goal = decision.goals[0]
    assert goal.result_contract == "response"
    assert goal.resource_hints[0].user_required_provider == "notion"
    assert set(goal.resource_hints[0].operations) == {"search", "read"}

    task = GoalGraphCompiler().compile(decision, decision.user_goal).task_spec
    assert task.resource_requirements[0].semantic_domain == "workspace"
    assert task.resource_requirements[0].required_providers == ("notion",)
    assert task.constraints.read_only


def test_notion_write_becomes_governed_generic_action():
    decision = _notion_analysis("external_state", ["create"])
    assert decision.goals[0].result_contract == "external_state"

    interpretation = GoalGraphCompiler().compile(decision, decision.user_goal)
    assert interpretation.ledger.items[0].result_contract == "external_state"
    assert interpretation.task_spec.mutation_intent is not None
    assert not interpretation.task_spec.constraints.read_only


def _notion_analysis(result_contract, operations):
    return TaskAnalysis(
        user_goal="处理 Orion 项目页面",
        goals=[Goal(
            goal_id="goal_1",
            result_contract=result_contract,
            description="处理 Orion 项目页面",
            side_effect_intent="mutation" if result_contract == "external_state" else "none",
            resource_hints=[ResourceHint(
                semantic_domain="workspace",
                resource_types=["page"],
                operations=operations,
                user_required_provider="notion",
                origin="user_explicit",
            )],
        )],
    )
