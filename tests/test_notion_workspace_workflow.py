from __future__ import annotations

from personal_agent.kernel.models import EntryInput
from personal_agent.planning.router import DefaultIntentRouter
from personal_agent.planning.workflow import WORKFLOW_REGISTRY


def test_notion_workspace_question_routes_to_notion_workflow():
    decision = DefaultIntentRouter(None).classify(EntryInput(
        text="在 Notion 里搜索 Orion 项目的会议纪要",
        user_id="test",
    ))

    assert decision.primary_intent == "notion_workspace_qa"
    assert decision.route_type == "single_workflow"


def test_notion_write_request_does_not_route_to_read_only_workflow():
    decision = DefaultIntentRouter(None).classify(EntryInput(
        text="在 Notion 创建一个 Orion 项目总结页面",
        user_id="test",
    ))

    assert decision.primary_intent != "notion_workspace_qa"


def test_notion_workspace_workflow_uses_react_and_read_only_notion_tools():
    spec = WORKFLOW_REGISTRY.select("notion_workspace_qa")
    by_id = {step.step_id: step for step in spec.steps}

    assert spec.workflow_id == "notion_workspace_qa"
    assert [step.step_id for step in spec.steps] == ["notion-retrieve", "notion-compose"]
    assert by_id["notion-retrieve"].execution_mode == "react"
    assert by_id["notion-retrieve"].allowed_tools == (
        "notion.search",
        "notion.retrieve_page_markdown",
    )
    assert by_id["notion-compose"].depends_on == ("notion-retrieve",)
