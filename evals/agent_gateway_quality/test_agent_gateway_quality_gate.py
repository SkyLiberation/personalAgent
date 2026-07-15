from __future__ import annotations

import json
from pathlib import Path

from evals.agent_gateway_quality.dataset import load_cases
from evals.agent_gateway_quality.scorer import AgentGatewayQualityRun, score_all
from personal_agent.agents import AgentGateway
from personal_agent.governance.policy import PolicyEngine
from personal_agent.kernel.contracts.agent import (
    AgentArtifact,
    SubagentProfile,
    AgentEvent,
    AgentGatewayContext,
    AgentGovernance,
    AgentRun,
    AgentRunResult,
    AgentTask,
    new_agent_artifact_id,
    new_agent_event_id,
    new_agent_run_id,
)


def test_agent_gateway_quality_gate():
    cases = load_cases()
    runs = tuple(_run_case(case) for case in cases)
    report = score_all(cases, runs)
    baseline = json.loads(Path(__file__).with_name("baseline.json").read_text(encoding="utf-8"))
    failures = report.check_thresholds(baseline)
    assert not failures, "\n".join(failures)


def _run_case(case) -> AgentGatewayQualityRun:
    gateway = AgentGateway(policy_engine=PolicyEngine())
    gateway.register(_QualityAgent("gpt_researcher", permission_scope="a2a:gpt_researcher:research"))
    gateway.register(_QualityAgent("secondary_researcher", permission_scope="a2a:secondary:research"))
    context = AgentGatewayContext(
        user_id="quality",
        session_id=case.id,
        run_id=f"entry-{case.id}",
        task_id="agent-gateway-quality",
        goal_id=case.id,
        action_id=f"{case.id}:delegate",
        source_platform="agent_gateway_quality",
    )
    task = AgentTask(task_text="Agent2Agent adoption", task_type="research")

    if case.operation == "invoke":
        result = gateway.invoke(case.agent_id, task, context)
        run = result.run
        stream_events: tuple[str, ...] = ()
    elif case.operation == "submit_poll":
        submitted = gateway.submit(case.agent_id, task, context)
        run = gateway.poll(submitted.agent_run_id, context)
        stream_events = ()
    elif case.operation == "cancel":
        submitted = gateway.submit(case.agent_id, task, context)
        run = gateway.cancel(submitted.agent_run_id, context)
        stream_events = ()
    elif case.operation == "stream":
        submitted = gateway.submit(case.agent_id, task, context)
        stream = tuple(gateway.stream(submitted.agent_run_id, context))
        run = gateway.get_run(submitted.agent_run_id) or submitted
        stream_events = tuple(event.type for event in stream)
    elif case.operation == "multi_agent_selection":
        result = gateway.invoke(case.agent_id, task, context)
        run = result.run
        stream_events = ()
    else:
        raise AssertionError(f"unknown operation={case.operation!r}")

    definition = gateway.profile(run.agent_id)
    return AgentGatewayQualityRun(
        case_id=case.id,
        agent_id=run.agent_id,
        status=run.status,
        permission_scope=definition.governance.permission_scope if definition else "",
        artifact_statuses=tuple(artifact.producer_verification_status for artifact in run.artifacts),
        event_types=tuple(event.type for event in run.events),
        stream_event_types=stream_events,
    )


class _QualityAgent:
    def __init__(self, agent_id: str, *, permission_scope: str) -> None:
        self.profile = SubagentProfile(
            agent_id=agent_id,
            provider=agent_id,
            protocol="local",
            semantic_domains=("external_research",),
            task_types=("research",),
            governance=AgentGovernance(
                permission_scope=permission_scope,
                risk_level="medium",
                side_effects=("external_network",),
            ),
        )

    def invoke(self, task: AgentTask, context: AgentGatewayContext) -> AgentRunResult:
        run = self._run(task, context, status="completed")
        return AgentRunResult(run=run, output_text="quality report", artifacts=run.artifacts)

    def submit(self, task: AgentTask, context: AgentGatewayContext) -> AgentRun:
        return self._run(task, context, status="running")

    def poll(self, agent_run_id: str, context: AgentGatewayContext) -> AgentRun:
        return self._run(AgentTask("quality"), context, status="completed", agent_run_id=agent_run_id)

    def cancel(self, agent_run_id: str, context: AgentGatewayContext) -> AgentRun:
        return self._run(AgentTask("quality"), context, status="cancelled", agent_run_id=agent_run_id)

    def stream(self, agent_run_id: str, context: AgentGatewayContext):
        yield AgentEvent(
            event_id=new_agent_event_id(),
            agent_run_id=agent_run_id,
            type="stream_delta",
            payload={"delta": "quality"},
        )

    def _run(
        self,
        task: AgentTask,
        context: AgentGatewayContext,
        *,
        status: str,
        agent_run_id: str | None = None,
    ) -> AgentRun:
        run_id = agent_run_id or new_agent_run_id()
        artifact = AgentArtifact(
            artifact_id=new_agent_artifact_id(),
            agent_run_id=run_id,
            kind="markdown_report",
            content="quality report",
            producer_verification_status="unverified",
        )
        event = AgentEvent(
            event_id=new_agent_event_id(),
            agent_run_id=run_id,
            type="status_changed",
            payload={"status": status},
        )
        return AgentRun(
            agent_run_id=run_id,
            agent_id=self.profile.agent_id,
            status=status,  # type: ignore[arg-type]
            task=task,
            context=context,
            external_task_id="quality-task",
            result={"report": "quality report"},
            artifacts=(artifact,),
            events=(event,),
        )
