from __future__ import annotations

import pytest

from personal_agent.infra.structured_model import StructuredModelResponse
from personal_agent.orchestration.orchestration_models import StepRunState
from personal_agent.orchestration.orchestration_nodes._graph_helpers import (
    _topological_sort_steps,
)
from personal_agent.planning.router import Goal, RouterDecision
from personal_agent.planning.workflow_planner import GoalDependencyDecision, WorkflowPlanner
from personal_agent.kernel.config import Settings


class FakeDependencyModelClient:
    def __init__(self, dependencies: dict[str, list[str]]) -> None:
        self.dependencies = dependencies
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        return StructuredModelResponse(
            value=request.output_type(
                decisions=[
                    GoalDependencyDecision(
                        task_id=task_id,
                        depends_on=depends_on,
                        reason="fixture",
                        confidence=1.0,
                    )
                    for task_id, depends_on in self.dependencies.items()
                ]
            ),
            model="fake",
            latency_ms=0.0,
        )


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


def test_planner_keeps_independent_read_only_goals_unlinked():
    planner = WorkflowPlanner(Settings())
    decision = RouterDecision(goals=[
        Goal(goal_id="first", intent="ask", input="第一个问题"),
        Goal(goal_id="second", intent="ask", input="第二个问题"),
        Goal(goal_id="third", intent="ask", input="第三个问题"),
    ])

    plan, steps = planner.plan(decision, entry_text="连续问题")

    assert [task.task_id for task in plan.tasks] == ["first", "second", "third"]
    assert [task.depends_on for task in plan.tasks] == [[], [], []]
    second_root = next(step for step in steps if step.step_id == "second::ask-retrieve")
    third_root = next(step for step in steps if step.step_id == "third::ask-retrieve")
    assert second_root.depends_on == []
    assert third_root.depends_on == []


def test_planner_links_continuation_goal_to_previous_task():
    planner = WorkflowPlanner(Settings())
    decision = RouterDecision(goals=[
        Goal(goal_id="first", intent="ask", input="DNS 为什么需要缓存？"),
        Goal(goal_id="second", intent="ask", input="继续解释这个问题的边界场景"),
    ])

    plan, steps = planner.plan(decision, entry_text="连续问题")

    assert [task.depends_on for task in plan.tasks] == [[], ["first"]]
    second_root = next(step for step in steps if step.step_id == "second::ask-retrieve")
    assert second_root.depends_on == ["first::ask-verify"]


def test_planner_uses_model_dependency_decision_for_semantic_followup():
    model_client = FakeDependencyModelClient({"second": ["first"]})
    planner = WorkflowPlanner(Settings(), dependency_model_client=model_client)
    decision = RouterDecision(goals=[
        Goal(goal_id="first", intent="ask", input="什么是数据库索引？"),
        Goal(goal_id="second", intent="ask", input="围绕第一点展开它和缓存的区别"),
    ])

    plan, steps = planner.plan(decision, entry_text="复合问题")

    assert model_client.calls == 1
    assert [task.depends_on for task in plan.tasks] == [[], ["first"]]
    second_root = next(step for step in steps if step.step_id == "second::ask-retrieve")
    assert second_root.depends_on == ["first::ask-verify"]


def test_planner_topologically_sorts_model_task_dag():
    model_client = FakeDependencyModelClient({"question": ["save"], "save": []})
    planner = WorkflowPlanner(Settings(), dependency_model_client=model_client)
    decision = RouterDecision(goals=[
        Goal(goal_id="question", intent="ask", input="基于保存的 DNS 知识解释缓存"),
        Goal(goal_id="save", intent="capture_text", input="DNS 会把域名解析为 IP。"),
    ])

    plan, steps = planner.plan(decision, entry_text="复合问题")

    assert [task.task_id for task in plan.tasks] == ["save", "question"]
    assert plan.tasks[1].depends_on == ["save"]
    assert [step.step_id for step in steps] == [
        "save::cap-structure",
        "question::ask-retrieve",
        "question::ask-compose",
        "question::ask-verify",
    ]
    question_root = next(step for step in steps if step.step_id == "question::ask-retrieve")
    assert question_root.depends_on == ["save::cap-structure"]


def test_planner_rejects_unknown_model_dependencies():
    model_client = FakeDependencyModelClient({
        "second": ["missing"],
    })
    planner = WorkflowPlanner(Settings(), dependency_model_client=model_client)
    decision = RouterDecision(goals=[
        Goal(goal_id="first", intent="ask", input="第一个问题"),
        Goal(goal_id="second", intent="ask", input="第二个问题"),
    ])

    with pytest.raises(ValueError, match="unknown task"):
        planner.plan(decision, entry_text="复合问题")


def test_planner_rejects_task_dependency_cycles():
    model_client = FakeDependencyModelClient({
        "first": ["second"],
        "second": ["first"],
    })
    planner = WorkflowPlanner(Settings(), dependency_model_client=model_client)
    decision = RouterDecision(goals=[
        Goal(goal_id="first", intent="ask", input="第一个问题"),
        Goal(goal_id="second", intent="ask", input="第二个问题"),
    ])

    with pytest.raises(ValueError, match="dependency cycle"):
        planner.plan(decision, entry_text="复合问题")


def test_planner_serializes_longterm_mutations():
    planner = WorkflowPlanner(Settings())
    decision = RouterDecision(goals=[
        Goal(goal_id="first", intent="capture_text", input="第一条知识"),
        Goal(goal_id="second", intent="capture_text", input="第二条知识"),
    ])

    plan, steps = planner.plan(decision, entry_text="连续保存")

    assert [task.depends_on for task in plan.tasks] == [[], ["first"]]
    second_step = next(step for step in steps if step.step_id == "second::cap-structure")
    assert second_step.depends_on == ["first::cap-structure"]


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


def test_step_topological_sort_rejects_dependency_cycles():
    steps = [
        StepRunState(step_id="a", depends_on=["b"]),
        StepRunState(step_id="b", depends_on=["a"]),
    ]

    with pytest.raises(ValueError, match="dependency cycle"):
        _topological_sort_steps(steps)


def test_step_topological_sort_rejects_unknown_dependencies():
    steps = [StepRunState(step_id="a", depends_on=["missing"])]

    with pytest.raises(ValueError, match="unknown step"):
        _topological_sort_steps(steps)
