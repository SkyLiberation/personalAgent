from __future__ import annotations

from personal_agent.governance import ToolExecutor
from personal_agent.infra.a2a import A2AResearchResponse
from personal_agent.kernel.config_models import GPTResearcherA2AConfig
from personal_agent.tools import build_gpt_researcher_a2a_tool, tool_governance


class FakeGPTResearcherA2AClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def research(self, **kwargs):
        self.calls.append(kwargs)
        return A2AResearchResponse(
            task_id="task-1",
            context_id="context-1",
            state="completed",
            report="# Report\n\nAgent2Agent protocol adoption.",
            artifacts=[],
            metadata={"md_path": "/outputs/task.md"},
            raw={"id": "task-1"},
        )


def test_gpt_researcher_a2a_tool_returns_report_artifact_through_gateway():
    client = FakeGPTResearcherA2AClient()
    tool = build_gpt_researcher_a2a_tool(GPTResearcherA2AConfig(), client)
    executor = ToolExecutor()
    executor.register(tool)

    result = executor.invoke_direct(
        "gpt_researcher.a2a_research",
        topic="Agent2Agent protocol adoption",
        user_id="alice",
    )

    assert result["ok"] is True
    assert result["data"]["provider"] == "gpt_researcher_a2a"
    assert result["data"]["task_id"] == "task-1"
    assert "Agent2Agent" in result["data"]["report"]
    assert client.calls[0]["topic"] == "Agent2Agent protocol adoption"


def test_gpt_researcher_a2a_tool_governance_is_external_medium_risk():
    tool = build_gpt_researcher_a2a_tool(GPTResearcherA2AConfig())
    governance = tool_governance(tool)

    assert governance.exposure == "public_agent"
    assert governance.risk_level == "medium"
    assert governance.side_effects == ("external_network",)
    assert governance.permission_scope == "a2a:gpt_researcher:research"
    assert governance.rate_limit_per_minute == 5
