from __future__ import annotations

from personal_agent.kernel.models import EntryInput
from personal_agent.planning.router import DefaultIntentRouter
from personal_agent.planning.workflow import WORKFLOW_REGISTRY


def test_gpt_researcher_a2a_request_routes_to_a2a_workflow():
    decision = DefaultIntentRouter(None).classify(EntryInput(
        text="用 GPT Researcher A2A 调研 Agent2Agent 协议采用情况，并生成研究报告",
        user_id="test",
    ))

    assert decision.primary_intent == "gpt_researcher_a2a"
    assert decision.route_type == "single_workflow"


def test_generic_research_request_stays_on_internal_research_workflow():
    decision = DefaultIntentRouter(None).classify(EntryInput(
        text="调研最近一个月 Agent 工具调用的发展，最多 2 条，高可信",
        user_id="test",
    ))

    assert decision.primary_intent == "research_once"


def test_gpt_researcher_a2a_workflow_uses_deterministic_tool_gateway_step():
    spec = WORKFLOW_REGISTRY.select("gpt_researcher_a2a")
    by_id = {step.step_id: step for step in spec.steps}

    assert spec.workflow_id == "gpt_researcher_a2a"
    assert [step.step_id for step in spec.steps] == [
        "gptr-a2a-research",
        "gptr-a2a-compose",
    ]
    assert by_id["gptr-a2a-research"].action_type == "tool_call"
    assert by_id["gptr-a2a-research"].tool_name == "gpt_researcher.a2a_research"
    assert by_id["gptr-a2a-research"].risk_level == "medium"
    assert by_id["gptr-a2a-research"].side_effects == ("external_network",)
    assert by_id["gptr-a2a-compose"].depends_on == ("gptr-a2a-research",)
