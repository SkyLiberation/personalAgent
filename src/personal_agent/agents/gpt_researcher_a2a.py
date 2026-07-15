from __future__ import annotations

from dataclasses import replace
from typing import Iterator, Protocol

from personal_agent.infra.a2a import A2AResearchResponse, GPTResearcherA2AClient
from personal_agent.kernel.config_models import GPTResearcherA2AConfig
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


class GPTResearcherA2AProtocol(Protocol):
    def research(
        self,
        *,
        topic: str,
        report_type: str | None = None,
        report_source: str | None = None,
        tone: str | None = None,
        max_search_results: int | None = None,
        blocking: bool = True,
    ) -> A2AResearchResponse: ...

    def submit_research(
        self,
        *,
        topic: str,
        report_type: str | None = None,
        report_source: str | None = None,
        tone: str | None = None,
        max_search_results: int | None = None,
    ) -> A2AResearchResponse: ...

    def get_task(self, task_id: str) -> A2AResearchResponse: ...

    def cancel_task(self, task_id: str) -> A2AResearchResponse: ...

    def stream_task(self, task_id: str): ...


class GPTResearcherA2AAdapter:
    def __init__(
        self,
        config: GPTResearcherA2AConfig,
        client: GPTResearcherA2AProtocol | None = None,
    ) -> None:
        self._config = config
        self._client = client or GPTResearcherA2AClient(config)
        self.profile = SubagentProfile(
            agent_id="gpt_researcher",
            provider="gpt_researcher",
            protocol="a2a_jsonrpc",
            description="GPT Researcher A2A deep research agent.",
            semantic_domains=("external_research", "web_research"),
            task_types=("research",),
            capability_ids=("agent:gpt_researcher",),
            allowed_operations=("delegate",),
            governance=AgentGovernance(
                risk_level="medium",
                side_effects=("external_network",),
                permission_scope="a2a:gpt_researcher:research",
                data_egress_class="content",
                trust_level="external",
                timeout_seconds=config.timeout_seconds,
                rate_limit_per_minute=5,
                allowed_domains=("localhost", "127.0.0.1"),
            ),
        )

    def invoke(self, task: AgentTask, context: AgentGatewayContext) -> AgentRunResult:
        response = self._client.research(**self._request_kwargs(task), blocking=True)
        run = self._run_from_response(task, context, response)
        output_text = response.report
        return AgentRunResult(
            run=run,
            output_text=output_text,
            artifacts=run.artifacts,
            metadata=response.metadata,
        )

    def submit(self, task: AgentTask, context: AgentGatewayContext) -> AgentRun:
        response = self._client.submit_research(**self._request_kwargs(task))
        status = _status_from_a2a(response.state)
        if status == "completed":
            status = "running"
        return replace(self._run_from_response(task, context, response), status=status)

    def poll(self, agent_run_id: str, context: AgentGatewayContext) -> AgentRun:
        task_id = _external_task_id(agent_run_id)
        response = self._client.get_task(task_id)
        task = AgentTask(task_text="", task_type="research")
        return self._run_from_response(task, context, response, agent_run_id=agent_run_id)

    def cancel(self, agent_run_id: str, context: AgentGatewayContext) -> AgentRun:
        task_id = _external_task_id(agent_run_id)
        response = self._client.cancel_task(task_id)
        task = AgentTask(task_text="", task_type="research")
        return replace(
            self._run_from_response(task, context, response, agent_run_id=agent_run_id),
            status="cancelled",
        )

    def stream(self, agent_run_id: str, context: AgentGatewayContext) -> Iterator[AgentEvent]:
        task_id = _external_task_id(agent_run_id)
        for item in self._client.stream_task(task_id):
            yield AgentEvent(
                event_id=new_agent_event_id(),
                agent_run_id=agent_run_id,
                type="stream_delta",
                payload=dict(item),
            )

    def _request_kwargs(self, task: AgentTask) -> dict[str, object]:
        data = {**task.metadata, **task.input}
        topic = str(data.get("topic") or task.task_text).strip()
        kwargs: dict[str, object] = {"topic": topic}
        for key in ("report_type", "report_source", "tone", "max_search_results"):
            if data.get(key) is not None:
                kwargs[key] = data[key]
        return kwargs

    def _run_from_response(
        self,
        task: AgentTask,
        context: AgentGatewayContext,
        response: A2AResearchResponse,
        *,
        agent_run_id: str | None = None,
    ) -> AgentRun:
        resolved_run_id = agent_run_id or _agent_run_id(response.task_id)
        artifacts = tuple(_artifact_from_a2a(resolved_run_id, item, response.report) for item in response.artifacts)
        if not artifacts and response.report:
            artifacts = (
                AgentArtifact(
                    artifact_id=new_agent_artifact_id(),
                    agent_run_id=resolved_run_id,
                    kind="markdown_report",
                    content=response.report,
                    payload={"source": "status.message"},
                    producer_verification_status="unverified",
                ),
            )
        status = _status_from_a2a(response.state)
        events = (
            AgentEvent(
                event_id=new_agent_event_id(),
                agent_run_id=resolved_run_id,
                type="status_changed",
                payload={"state": response.state, "status": status},
            ),
        )
        return AgentRun(
            agent_run_id=resolved_run_id,
            agent_id=self.profile.agent_id,
            status=status,
            task=task,
            context=context,
            external_task_id=response.task_id,
            result={
                "provider": "gpt_researcher_a2a",
                "task_id": response.task_id,
                "context_id": response.context_id,
                "state": response.state,
                "report": response.report,
                "metadata": response.metadata,
                "raw": response.raw,
            },
            artifacts=artifacts,
            events=events,
        )


def _artifact_from_a2a(agent_run_id: str, raw: dict, report: str) -> AgentArtifact:
    content = report
    for part in raw.get("parts") or []:
        if isinstance(part, dict) and part.get("kind") == "text":
            content = str(part.get("text") or content)
            break
    return AgentArtifact(
        artifact_id=new_agent_artifact_id(),
        agent_run_id=agent_run_id,
        kind=str(raw.get("name") or raw.get("kind") or "a2a_artifact"),
        content=content,
        payload=raw,
        producer_verification_status="unverified",
    )


def _status_from_a2a(state: str) -> str:
    normalized = state.lower()
    if normalized in {"completed", "succeeded", "done"}:
        return "completed"
    if normalized in {"failed", "error"}:
        return "failed"
    if normalized in {"canceled", "cancelled"}:
        return "cancelled"
    return "running"


def _agent_run_id(task_id: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in task_id)[:48]
    return f"arun_{safe}" if safe else new_agent_run_id()


def _external_task_id(agent_run_id: str) -> str:
    return agent_run_id.removeprefix("arun_").replace("_", "-")


__all__ = ["GPTResearcherA2AAdapter", "GPTResearcherA2AProtocol"]
