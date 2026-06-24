from __future__ import annotations

import pytest

from personal_agent.agent.router import Goal, RouterDecision
from personal_agent.agent.workflow_planner import WorkflowPlanner
from personal_agent.kernel.config import Settings


def test_planner_compiles_ingest_then_ask_workflows():
    planner = WorkflowPlanner(Settings())
    decision = RouterDecision(goals=[
        Goal(goal_id="save", intent="capture_text", input="DNS 将域名解析为 IP。"),
        Goal(
            goal_id="question",
            intent="ask",
            input="DNS 为什么需要缓存？",
        ),
    ])

    plan, steps = planner.plan(decision, entry_text="compound request")

    assert [task.intent for task in plan.tasks] == ["capture_text", "ask"]
    assert [step.step_id for step in steps] == [
        "save::cap-structure",
        "question::ask-retrieve",
        "question::ask-compose",
        "question::ask-verify",
    ]
    assert steps[1].depends_on == ["save::cap-structure"]
    assert plan.tasks[1].depends_on == ["save"]
    assert plan.model_dump()["tasks"][0]["workflow_id"] == "capture_text"
    assert "steps" not in plan.model_dump()


def test_planner_derives_risk_and_confirmation_from_workflow():
    planner = WorkflowPlanner(Settings())
    _, steps = planner.plan(
        RouterDecision(goals=[Goal(goal_id="delete", intent="delete_knowledge")]),
        entry_text="删除 DNS 笔记",
    )
    delete_step = next(step for step in steps if step.tool_name == "delete_note")
    assert delete_step.risk_level == "high"
    assert delete_step.requires_confirmation is True


def test_planner_derives_dependencies_from_goal_order():
    planner = WorkflowPlanner(Settings())
    decision = RouterDecision(goals=[
        Goal(goal_id="first", intent="ask", input="第一个问题"),
        Goal(goal_id="second", intent="ask", input="第二个问题"),
        Goal(goal_id="third", intent="ask", input="第三个问题"),
    ])

    plan, steps = planner.plan(decision, entry_text="连续问题")

    assert [task.task_id for task in plan.tasks] == ["first", "second", "third"]
    assert [task.depends_on for task in plan.tasks] == [[], ["first"], ["second"]]
    second_root = next(step for step in steps if step.step_id == "second::ask-retrieve")
    third_root = next(step for step in steps if step.step_id == "third::ask-retrieve")
    assert second_root.depends_on == ["first::ask-verify"]
    assert third_root.depends_on == ["second::ask-verify"]


@pytest.mark.parametrize(
    ("intent", "tool_name"),
    [
        ("review_digest", "review_digest"),
        ("consolidate_knowledge", "consolidate_knowledge"),
        ("inspect_knowledge_gaps", "inspect_knowledge_gaps"),
    ],
)
def test_planner_compiles_proactive_knowledge_intents(intent, tool_name):
    planner = WorkflowPlanner(Settings())

    plan, steps = planner.plan(
        RouterDecision(goals=[Goal(goal_id="knowledge", intent=intent, input="缓存")]),
        entry_text="knowledge request",
    )

    assert plan.tasks[0].workflow_id == intent
    assert steps[0].tool_name == tool_name
    assert steps[-1].action_type == "compose"


def test_planner_rejects_duplicate_goal_ids():
    planner = WorkflowPlanner(Settings())
    decision = RouterDecision(goals=[
        Goal(goal_id="same", intent="capture_text", input="正文"),
        Goal(goal_id="same", intent="ask", input="问题"),
    ])

    with pytest.raises(ValueError, match="unique goal_id"):
        planner.plan(decision, entry_text="复合请求")
