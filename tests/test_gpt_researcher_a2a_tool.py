from __future__ import annotations

from personal_agent.agents.gpt_researcher_a2a import GPTResearcherA2AAdapter
from personal_agent.infra.a2a import A2AResearchResponse
from personal_agent.kernel.config_models import GPTResearcherA2AConfig
from personal_agent.kernel.contracts.agent import AgentGatewayContext, AgentTask


class FakeGPTResearcherA2AClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def research(self, **kwargs):
        self.calls.append(kwargs)
        return self._response(state="completed")

    def submit_research(self, **kwargs):
        self.calls.append(kwargs)
        return self._response(state="working")

    def get_task(self, task_id):
        return self._response(state="completed", task_id=task_id)

    def cancel_task(self, task_id):
        return self._response(state="canceled", task_id=task_id)

    def stream_task(self, task_id):
        yield {"kind": "text", "text": f"stream {task_id}"}

    def _response(self, *, state: str, task_id: str = "task-1") -> A2AResearchResponse:
        report = "# Report\n\nAgent2Agent protocol adoption."
        return A2AResearchResponse(
            task_id=task_id,
            context_id="context-1",
            state=state,
            report=report,
            artifacts=[{"name": "report", "parts": [{"kind": "text", "text": report}]}],
            metadata={"md_path": "/outputs/task.md"},
            raw={"id": task_id},
        )


def test_gpt_researcher_a2a_adapter_returns_agent_run_result():
    client = FakeGPTResearcherA2AClient()
    adapter = GPTResearcherA2AAdapter(GPTResearcherA2AConfig(), client)

    result = adapter.invoke(AgentTask("Agent2Agent protocol adoption"), _ctx())

    assert result.run.agent_id == "gpt_researcher"
    assert result.run.status == "completed"
    assert "Agent2Agent" in result.output_text
    assert result.artifacts[0].producer_verification_status == "unverified"
    assert client.calls[0]["topic"] == "Agent2Agent protocol adoption"


def test_gpt_researcher_a2a_adapter_governance_metadata():
    adapter = GPTResearcherA2AAdapter(GPTResearcherA2AConfig())
    governance = adapter.profile.governance

    assert adapter.profile.protocol == "a2a_jsonrpc"
    assert governance.risk_level == "medium"
    assert governance.side_effects == ("external_network",)
    assert governance.permission_scope == "a2a:gpt_researcher:research"
    assert governance.rate_limit_per_minute == 5


def _ctx() -> AgentGatewayContext:
    return AgentGatewayContext(
        user_id="alice",
        session_id="s1",
        run_id="entry-run",
        task_id="task",
        goal_id="research",
        action_id="delegate-research",
    )
