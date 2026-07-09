from __future__ import annotations

from personal_agent.kernel.models import EntryInput
from personal_agent.planning.router import DefaultIntentRouter
from personal_agent.planning.workflow import WORKFLOW_REGISTRY


def test_notion_workspace_question_routes_to_external_workspace_workflow():
    decision = DefaultIntentRouter(None).classify(EntryInput(
        text="在 Notion 里搜索 Orion 项目的会议纪要",
        user_id="test",
    ))

    assert decision.primary_intent == "external_workspace_qa"
    assert decision.route_type == "single_workflow"


def test_notion_write_request_does_not_route_to_read_only_workflow():
    decision = DefaultIntentRouter(None).classify(EntryInput(
        text="在 Notion 创建一个 Orion 项目总结页面",
        user_id="test",
    ))

    assert decision.primary_intent != "external_workspace_qa"


def test_external_workspace_workflow_uses_react_without_provider_allowlist():
    spec = WORKFLOW_REGISTRY.select("external_workspace_qa")
    by_id = {step.step_id: step for step in spec.steps}

    assert spec.workflow_id == "external_workspace_qa"
    assert [step.step_id for step in spec.steps] == ["workspace-resolve", "workspace-compose"]
    assert by_id["workspace-resolve"].execution_mode == "react"
    assert by_id["workspace-resolve"].allowed_tools == ()
    assert by_id["workspace-compose"].depends_on == ("workspace-resolve",)
