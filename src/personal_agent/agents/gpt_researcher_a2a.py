from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import Iterator, Protocol

from personal_agent.infra.a2a import A2AResearchResponse, GPTResearcherA2AClient
from personal_agent.kernel.config_models import GPTResearcherA2AConfig
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
    new_agent_event_id,
    new_agent_run_id,
)
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import ExecutionScope, SecurityScope


class AgentArtifactWriteProtocol(Protocol):
    def write_generated(
        self,
        *,
        security_scope: SecurityScope,
        execution_scope: ExecutionScope,
        producer_key: str,
        producer_ref: str,
        kind: str,
        content: str,
        content_digest: str,
        source_artifact_refs: tuple[ResourceRef, ...],
        evidence_refs: tuple[str, ...],
    ) -> ResourceRef: ...


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
        submission_key: str | None = None,
    ) -> A2AResearchResponse: ...

    def get_task(self, task_id: str) -> A2AResearchResponse: ...

    def cancel_task(self, task_id: str) -> A2AResearchResponse: ...

    def stream_task(self, task_id: str): ...


class GPTResearcherA2AAdapter:
    def __init__(
        self,
        config: GPTResearcherA2AConfig,
        artifact_writer: AgentArtifactWriteProtocol,
        client: GPTResearcherA2AProtocol | None = None,
    ) -> None:
        self._config = config
        self._client = client or GPTResearcherA2AClient(config)
        self._artifact_writer = artifact_writer
        self.profile = SubagentProfile(
            agent_id="gpt_researcher",
            provider="gpt_researcher",
            protocol="a2a_jsonrpc",
            description=(
                "Deep external research specialist for user requests that require researching authoritative "
                "web sources and returning an evidence-backed report for parent synthesis."
            ),
            semantic_domains=("external", "external_research", "web_research"),
            task_types=("research", "report"),
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

    def invoke(self, task: AgentTask, context: AgentGatewayContext) -> ChildAgentRunOutcome:
        raise RuntimeError("GPT Researcher is asynchronous; use AgentGateway.submit/poll")

    def submit(
        self,
        task: AgentTask,
        context: AgentGatewayContext,
        *,
        submission_key: str,
    ) -> ChildAgentRunRecord:
        response = self._client.submit_research(
            **self._request_kwargs(task, submission_key=submission_key)
        )
        status = _status_from_a2a(response.state)
        if status == "completed":
            status = "running"
        run = self._run_from_response(task, context, response)
        return replace(run, projection=replace(run.projection, status=status))

    def lookup_submission(
        self,
        submission_key: str,
        task: AgentTask,
        context: AgentGatewayContext,
    ) -> ChildAgentRunRecord | None:
        # The current GPT Researcher A2A contract has tasks/get by provider task
        # id, but no query by client submission key. Returning None is the
        # explicit fail-closed contract used after an uncertain submit outcome.
        return None

    def poll(self, run: ChildAgentRunRecord, context: AgentGatewayContext) -> ChildAgentRunRecord:
        task_id = _required_external_task_id(run)
        response = self._client.get_task(task_id)
        return self._run_from_response(
            run.definition.task, context, response,
            agent_run_id=run.definition.agent_run_id,
        )

    def cancel(self, run: ChildAgentRunRecord, context: AgentGatewayContext) -> ChildAgentRunRecord:
        task_id = _required_external_task_id(run)
        response = self._client.cancel_task(task_id)
        refreshed = self._run_from_response(
            run.definition.task, context, response,
            agent_run_id=run.definition.agent_run_id,
        )
        return replace(refreshed, projection=replace(refreshed.projection, status="cancelled"))

    def stream(self, run: ChildAgentRunRecord, context: AgentGatewayContext) -> Iterator[ChildAgentRunEvent]:
        task_id = _required_external_task_id(run)
        for item in self._client.stream_task(task_id):
            yield ChildAgentRunEvent(
                event_id=new_agent_event_id(),
                agent_run_id=run.definition.agent_run_id,
                type="stream_delta",
                payload=dict(item),
            )

    def _request_kwargs(
        self,
        task: AgentTask,
        *,
        submission_key: str,
    ) -> dict[str, object]:
        data = {**task.metadata, **task.input}
        topic = str(data.get("topic") or task.task_text).strip()
        kwargs: dict[str, object] = {
            "topic": topic,
            "submission_key": submission_key,
        }
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
    ) -> ChildAgentRunRecord:
        resolved_run_id = agent_run_id or _agent_run_id(response.task_id)
        artifacts = tuple(
            self._persist_artifact(
                resolved_run_id,
                context,
                response.task_id,
                item,
                response.report,
                index,
            )
            for index, item in enumerate(response.artifacts)
        )
        if not artifacts and response.report:
            content_digest = sha256(response.report.encode("utf-8")).hexdigest()
            artifact_ref = self._artifact_writer.write_generated(
                security_scope=context.execution_scope.security_scope,
                execution_scope=context.execution_scope,
                producer_key=(
                    f"agent:{self.profile.agent_id}:{response.task_id}:"
                    f"status-message:{content_digest}"
                ),
                producer_ref=response.task_id,
                kind="markdown_report",
                content=response.report,
                content_digest=content_digest,
                source_artifact_refs=(),
                evidence_refs=(),
            )
            artifacts = (
                AgentArtifact(
                    agent_run_id=resolved_run_id,
                    kind="markdown_report",
                    artifact_ref=artifact_ref,
                    producer_verification_status="unverified",
                ),
            )
        status = _status_from_a2a(response.state)
        events = (
            ChildAgentRunEvent(
                event_id=new_agent_event_id(),
                agent_run_id=resolved_run_id,
                type="status_changed",
                payload={"state": response.state, "status": status},
            ),
        )
        return ChildAgentRunRecord(
            definition=ChildAgentRunDefinition(
                agent_run_id=resolved_run_id,
                agent_id=self.profile.agent_id,
                task=task,
                context=context,
            ),
            projection=ChildAgentRunProjection(
                agent_run_id=resolved_run_id,
                status=status,
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
            ),
            artifact_index=ChildAgentArtifactIndex(
                agent_run_id=resolved_run_id,
                artifacts=artifacts,
            ),
            events=events,
        )

    def _persist_artifact(
        self,
        agent_run_id: str,
        context: AgentGatewayContext,
        provider_task_id: str,
        raw: dict,
        report: str,
        index: int,
    ) -> AgentArtifact:
        content = report
        for part in raw.get("parts") or []:
            if isinstance(part, dict) and part.get("kind") == "text":
                content = str(part.get("text") or content)
                break
        kind = str(raw.get("name") or raw.get("kind") or "a2a_artifact")
        content_digest = sha256(content.encode("utf-8")).hexdigest()
        artifact_ref = self._artifact_writer.write_generated(
            security_scope=context.execution_scope.security_scope,
            execution_scope=context.execution_scope,
            producer_key=(
                f"agent:{self.profile.agent_id}:{provider_task_id}:"
                f"{index}:{content_digest}"
            ),
            producer_ref=provider_task_id,
            kind=kind,
            content=content,
            content_digest=content_digest,
            source_artifact_refs=(),
            evidence_refs=(),
        )
        return AgentArtifact(
            agent_run_id=agent_run_id,
            kind=kind,
            artifact_ref=artifact_ref,
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


def _required_external_task_id(run: ChildAgentRunRecord) -> str:
    task_id = run.projection.external_task_id
    if not task_id:
        raise RuntimeError("ChildAgentRun has no canonical external_task_id")
    return task_id


__all__ = ["GPTResearcherA2AAdapter", "GPTResearcherA2AProtocol"]
