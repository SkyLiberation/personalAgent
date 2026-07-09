from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

from personal_agent.governance.policy import PolicyEngine, PolicyInput
from personal_agent.kernel.contracts.agent import (
    AgentAdapter,
    AgentArtifact,
    AgentDefinition,
    AgentEvent,
    AgentGatewayContext,
    AgentRun,
    AgentRunResult,
    AgentTask,
    new_agent_event_id,
)


class InMemoryAgentRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}

    def put(self, run: AgentRun) -> AgentRun:
        self._runs[run.agent_run_id] = run
        return run

    def get(self, agent_run_id: str) -> AgentRun | None:
        return self._runs.get(agent_run_id)

    def list(self, *, run_id: str | None = None, agent_id: str | None = None) -> tuple[AgentRun, ...]:
        runs = list(self._runs.values())
        if run_id is not None:
            runs = [run for run in runs if run.context.run_id == run_id]
        if agent_id is not None:
            runs = [run for run in runs if run.agent_id == agent_id]
        return tuple(runs)


class AgentGateway:
    def __init__(
        self,
        *,
        policy_engine: PolicyEngine,
        store: InMemoryAgentRunStore | None = None,
    ) -> None:
        self._policy_engine = policy_engine
        self._store = store or InMemoryAgentRunStore()
        self._adapters: dict[str, AgentAdapter] = {}

    def register(self, adapter: AgentAdapter) -> None:
        self._adapters[adapter.definition.agent_id] = adapter

    def definitions(self) -> tuple[AgentDefinition, ...]:
        return tuple(adapter.definition for adapter in self._adapters.values())

    def definition(self, agent_id: str) -> AgentDefinition | None:
        adapter = self._adapters.get(agent_id)
        return adapter.definition if adapter is not None else None

    def invoke(
        self,
        agent_id: str,
        task: AgentTask,
        context: AgentGatewayContext,
    ) -> AgentRunResult:
        adapter = self._adapter(agent_id)
        self._authorize(adapter.definition, context, execution_mode="deterministic")
        result = adapter.invoke(task, context)
        run = self._append_event(result.run, "completed", {"status": result.run.status})
        run = replace(run, artifacts=tuple(_unverified(artifact) for artifact in result.artifacts))
        self._store.put(run)
        return AgentRunResult(
            run=run,
            output_text=result.output_text,
            artifacts=run.artifacts,
            metadata=result.metadata,
        )

    def submit(
        self,
        agent_id: str,
        task: AgentTask,
        context: AgentGatewayContext,
    ) -> AgentRun:
        adapter = self._adapter(agent_id)
        self._authorize(adapter.definition, context, execution_mode="deterministic")
        run = adapter.submit(task, context)
        run = self._append_event(run, "submitted", {"status": run.status})
        return self._store.put(run)

    def poll(self, agent_run_id: str, context: AgentGatewayContext) -> AgentRun:
        stored = self._require_run(agent_run_id)
        adapter = self._adapter(stored.agent_id)
        self._authorize(adapter.definition, context, execution_mode="deterministic")
        run = adapter.poll(agent_run_id, context)
        return self._store.put(_merge_events(stored, run))

    def cancel(self, agent_run_id: str, context: AgentGatewayContext) -> AgentRun:
        stored = self._require_run(agent_run_id)
        adapter = self._adapter(stored.agent_id)
        self._authorize(adapter.definition, context, execution_mode="deterministic")
        run = adapter.cancel(agent_run_id, context)
        run = self._append_event(_merge_events(stored, run), "canceled", {"status": run.status})
        return self._store.put(run)

    def stream(self, agent_run_id: str, context: AgentGatewayContext) -> Iterator[AgentEvent]:
        stored = self._require_run(agent_run_id)
        adapter = self._adapter(stored.agent_id)
        self._authorize(adapter.definition, context, execution_mode="deterministic")
        for event in adapter.stream(agent_run_id, context):
            current = self._store.get(agent_run_id) or stored
            self._store.put(replace(current, events=(*current.events, event)))
            yield event

    def get_run(self, agent_run_id: str) -> AgentRun | None:
        return self._store.get(agent_run_id)

    def list_runs(self, *, run_id: str | None = None, agent_id: str | None = None) -> tuple[AgentRun, ...]:
        return self._store.list(run_id=run_id, agent_id=agent_id)

    def _adapter(self, agent_id: str) -> AgentAdapter:
        adapter = self._adapters.get(agent_id)
        if adapter is None:
            raise KeyError(f"Unknown agent_id={agent_id!r}.")
        return adapter

    def _require_run(self, agent_run_id: str) -> AgentRun:
        run = self._store.get(agent_run_id)
        if run is None:
            raise KeyError(f"Unknown agent_run_id={agent_run_id!r}.")
        return run

    def _authorize(
        self,
        definition: AgentDefinition,
        context: AgentGatewayContext,
        *,
        execution_mode: str,
    ) -> None:
        governance = definition.governance
        decision = self._policy_engine.evaluate(PolicyInput(
            action="agent_call",
            user_id=context.user_id,
            session_id=context.session_id,
            source_platform=context.source_platform,
            execution_mode=execution_mode,
            tool_name=definition.agent_id,
            risk_level=governance.risk_level,  # type: ignore[arg-type]
            requires_confirmation=False,
            side_effects=governance.side_effects,  # type: ignore[arg-type]
            permission_scope=governance.permission_scope,
            confirmed=context.confirmed,
        ))
        if not decision.allowed:
            raise PermissionError(decision.reason or f"Agent {definition.agent_id} is not allowed.")

    @staticmethod
    def _append_event(run: AgentRun, event_type, payload: dict[str, object]) -> AgentRun:
        return replace(run, events=(*run.events, AgentEvent(
            event_id=new_agent_event_id(),
            agent_run_id=run.agent_run_id,
            type=event_type,
            payload=payload,
        )))


def _merge_events(stored: AgentRun, fresh: AgentRun) -> AgentRun:
    known = {event.event_id for event in stored.events}
    new_events = tuple(event for event in fresh.events if event.event_id not in known)
    return replace(fresh, events=(*stored.events, *new_events))


def _unverified(artifact: AgentArtifact) -> AgentArtifact:
    return replace(artifact, verification_status="unverified")


__all__ = ["AgentGateway", "InMemoryAgentRunStore"]
