from __future__ import annotations

from personal_agent.kernel.models import EntryInput
from personal_agent.planning.router import DefaultIntentRouter
from personal_agent.planning.workflow import WORKFLOW_REGISTRY


def test_github_repository_question_routes_to_external_codebase_workflow():
    decision = DefaultIntentRouter(None).classify(EntryInput(
        text="在 github/github-mcp-server 里 search_code 是在哪里实现的？",
        user_id="test",
    ))

    assert decision.primary_intent == "external_codebase_qa"
    assert decision.route_type == "single_workflow"


def test_personal_memory_question_does_not_route_to_external_codebase_workflow():
    decision = DefaultIntentRouter(None).classify(EntryInput(
        text="我之前关于 Agent tool use 的笔记里有哪些结论？",
        user_id="test",
    ))

    assert decision.primary_intent == "ask"


def test_external_codebase_workflow_uses_react_without_provider_allowlist():
    spec = WORKFLOW_REGISTRY.select("external_codebase_qa")
    by_id = {step.step_id: step for step in spec.steps}

    assert spec.workflow_id == "external_codebase_qa"
    assert [step.step_id for step in spec.steps] == ["codebase-resolve", "codebase-compose"]
    assert by_id["codebase-resolve"].execution_mode == "react"
    assert by_id["codebase-resolve"].allowed_tools == ()
    assert by_id["codebase-compose"].depends_on == ("codebase-resolve",)
