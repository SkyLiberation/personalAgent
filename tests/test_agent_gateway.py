from __future__ import annotations

from personal_agent.agents import AgentGateway
from personal_agent.governance.policy import PolicyEngine
from personal_agent.kernel.contracts.agent import (
    AgentArtifact,
    ChildAgentArtifactIndex,
    ChildAgentRunDefinition,
    ChildAgentRunRecord,
    SubagentProfile,
    ChildAgentRunEvent,
    AgentGatewayContext,
    AgentGovernance,
    ChildAgentRunProjection,
    ChildAgentRunOutcome,
    AgentTask,
    new_agent_artifact_id,
    new_agent_event_id,
    new_agent_run_id,
)


def test_agent_gateway_invoke_records_unverified_artifact():
    gateway = AgentGateway(policy_engine=PolicyEngine())
    gateway.register(_FakeAgent("researcher", output="report"))

    result = gateway.invoke("researcher", AgentTask("topic"), _ctx())

    assert result.run.projection.status == "completed"
    assert result.run.definition.agent_id == "researcher"
    assert result.run.artifact_index.artifacts[0].producer_verification_status == "unverified"
    assert gateway.get_run(result.run.definition.agent_run_id) is not None


def test_agent_gateway_submit_poll_cancel_and_stream():
    gateway = AgentGateway(policy_engine=PolicyEngine())
    gateway.register(_FakeAgent("researcher", output="report"))

    submitted = gateway.submit("researcher", AgentTask("topic"), _ctx())
    assert submitted.projection.status == "running"

    polled = gateway.poll(submitted.definition.agent_run_id, _ctx())
    assert polled.projection.status == "completed"

    stream = list(gateway.stream(submitted.definition.agent_run_id, _ctx()))
    assert [event.type for event in stream] == ["stream_delta"]

    canceled = gateway.cancel(submitted.definition.agent_run_id, _ctx())
    assert canceled.projection.status == "cancelled"


def test_agent_gateway_keeps_multiple_agent_definitions_separate():
    gateway = AgentGateway(policy_engine=PolicyEngine())
    gateway.register(_FakeAgent("researcher", output="research"))
    gateway.register(_FakeAgent("writer", output="write"))

    assert {item.agent_id for item in gateway.profiles()} == {"researcher", "writer"}
    result = gateway.invoke("writer", AgentTask("draft"), _ctx())

    assert result.run.definition.agent_id == "writer"
    assert result.output_text == "write"


def _ctx() -> AgentGatewayContext:
    return AgentGatewayContext(
        user_id="u1",
        session_id="s1",
        run_id="entry-run-1",
        task_id="task",
        goal_id="goal",
        action_id="action",
        source_platform="test",
    )


class _FakeAgent:
    def __init__(self, agent_id: str, *, output: str) -> None:
        self.profile = SubagentProfile(
            agent_id=agent_id,
            provider=agent_id,
            protocol="local",
            task_types=("research",),
            governance=AgentGovernance(permission_scope=f"a2a:{agent_id}:invoke"),
        )
        self._output = output

    def invoke(self, task: AgentTask, context: AgentGatewayContext) -> ChildAgentRunOutcome:
        run = self._run(task, context, status="completed")
        return ChildAgentRunOutcome(run=run, output_text=self._output)

    def submit(self, task: AgentTask, context: AgentGatewayContext) -> ChildAgentRunRecord:
        return self._run(task, context, status="running")

    def poll(self, agent_run_id: str, context: AgentGatewayContext) -> ChildAgentRunRecord:
        return self._run(AgentTask("topic"), context, status="completed", agent_run_id=agent_run_id)

    def cancel(self, agent_run_id: str, context: AgentGatewayContext) -> ChildAgentRunRecord:
        return self._run(AgentTask("topic"), context, status="cancelled", agent_run_id=agent_run_id)

    def stream(self, agent_run_id: str, context: AgentGatewayContext):
        yield ChildAgentRunEvent(
            event_id=new_agent_event_id(),
            agent_run_id=agent_run_id,
            type="stream_delta",
            payload={"delta": self._output},
        )

    def _run(
        self,
        task: AgentTask,
        context: AgentGatewayContext,
        *,
        status: str,
        agent_run_id: str | None = None,
    ) -> ChildAgentRunRecord:
        run_id = agent_run_id or new_agent_run_id()
        artifact = AgentArtifact(
            artifact_id=new_agent_artifact_id(),
            agent_run_id=run_id,
            kind="markdown_report",
            content=self._output,
        )
        return ChildAgentRunRecord(
            definition=ChildAgentRunDefinition(
                agent_run_id=run_id,
                agent_id=self.profile.agent_id,
                task=task,
                context=context,
            ),
            projection=ChildAgentRunProjection(
                agent_run_id=run_id,
                status=status,  # type: ignore[arg-type]
                external_task_id="task-1",
                result={"answer": self._output},
            ),
            artifact_index=ChildAgentArtifactIndex(
                agent_run_id=run_id,
                artifacts=(artifact,),
            ),
        )
