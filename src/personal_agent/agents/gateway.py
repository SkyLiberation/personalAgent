from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

from personal_agent.governance.policy import PolicyEngine, PolicyInput
from personal_agent.kernel.contracts.agent import (
    AgentAdapter,
    AgentArtifact,
    ChildAgentArtifactIndex,
    ChildAgentRunRecord,
    SubagentProfile,
    ChildAgentRunEvent,
    AgentGatewayContext,
    ChildAgentRunOutcome,
    AgentTask,
    new_agent_event_id,
)


class InMemoryAgentRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, ChildAgentRunRecord] = {}

    def put(self, run: ChildAgentRunRecord) -> ChildAgentRunRecord:
        self._runs[run.definition.agent_run_id] = run
        return run

    def get(self, agent_run_id: str) -> ChildAgentRunRecord | None:
        return self._runs.get(agent_run_id)

    def list(self, *, run_id: str | None = None, agent_id: str | None = None) -> tuple[ChildAgentRunRecord, ...]:
        runs = list(self._runs.values())
        if run_id is not None:
            runs = [run for run in runs if run.definition.context.run_id == run_id]
        if agent_id is not None:
            runs = [run for run in runs if run.definition.agent_id == agent_id]
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
        self._adapters[adapter.profile.agent_id] = adapter

    def profiles(self) -> tuple[SubagentProfile, ...]:
        return tuple(adapter.profile for adapter in self._adapters.values())

    def profile(self, agent_id: str) -> SubagentProfile | None:
        adapter = self._adapters.get(agent_id)
        return adapter.profile if adapter is not None else None

    def invoke(
        self,
        agent_id: str,
        task: AgentTask,
        context: AgentGatewayContext,
    ) -> ChildAgentRunOutcome:
        adapter = self._adapter(agent_id)
        self._authorize(adapter.profile, context, execution_mode="deterministic")
        result = adapter.invoke(task, context)
        run = self._append_event(
            result.run, "completed", {"status": result.run.projection.status},
        )
        run = replace(run, artifact_index=ChildAgentArtifactIndex(
            agent_run_id=run.definition.agent_run_id,
            artifacts=tuple(
                _unverified(artifact) for artifact in run.artifact_index.artifacts
            ),
        ))
        self._store.put(run)
        return ChildAgentRunOutcome(
            run=run,
            output_text=result.output_text,
            metadata=result.metadata,
        )

    def submit(
        self,
        agent_id: str,
        task: AgentTask,
        context: AgentGatewayContext,
    ) -> ChildAgentRunRecord:
        adapter = self._adapter(agent_id)
        self._authorize(adapter.profile, context, execution_mode="deterministic")
        run = adapter.submit(task, context)
        run = self._append_event(run, "submitted", {"status": run.projection.status})
        return self._store.put(run)

    def poll(self, agent_run_id: str, context: AgentGatewayContext) -> ChildAgentRunRecord:
        stored = self._require_run(agent_run_id)
        adapter = self._adapter(stored.definition.agent_id)
        self._authorize(adapter.profile, context, execution_mode="deterministic")
        run = adapter.poll(agent_run_id, context)
        return self._store.put(_merge_events(stored, run))

    def cancel(self, agent_run_id: str, context: AgentGatewayContext) -> ChildAgentRunRecord:
        stored = self._require_run(agent_run_id)
        adapter = self._adapter(stored.definition.agent_id)
        self._authorize(adapter.profile, context, execution_mode="deterministic")
        run = adapter.cancel(agent_run_id, context)
        run = self._append_event(
            _merge_events(stored, run), "cancelled", {"status": run.projection.status},
        )
        return self._store.put(run)

    def stream(self, agent_run_id: str, context: AgentGatewayContext) -> Iterator[ChildAgentRunEvent]:
        stored = self._require_run(agent_run_id)
        adapter = self._adapter(stored.definition.agent_id)
        self._authorize(adapter.profile, context, execution_mode="deterministic")
        for event in adapter.stream(agent_run_id, context):
            current = self._store.get(agent_run_id) or stored
            self._store.put(replace(current, events=(*current.events, event)))
            yield event

    def get_run(self, agent_run_id: str) -> ChildAgentRunRecord | None:
        return self._store.get(agent_run_id)

    def list_runs(self, *, run_id: str | None = None, agent_id: str | None = None) -> tuple[ChildAgentRunRecord, ...]:
        return self._store.list(run_id=run_id, agent_id=agent_id)

    def _adapter(self, agent_id: str) -> AgentAdapter:
        adapter = self._adapters.get(agent_id)
        if adapter is None:
            raise KeyError(f"Unknown agent_id={agent_id!r}.")
        return adapter

    def _require_run(self, agent_run_id: str) -> ChildAgentRunRecord:
        run = self._store.get(agent_run_id)
        if run is None:
            raise KeyError(f"Unknown agent_run_id={agent_run_id!r}.")
        return run

    def _authorize(
        self,
        definition: SubagentProfile,
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
    def _append_event(run: ChildAgentRunRecord, event_type, payload: dict[str, object]) -> ChildAgentRunRecord:
        return replace(run, events=(*run.events, ChildAgentRunEvent(
            event_id=new_agent_event_id(),
            agent_run_id=run.definition.agent_run_id,
            type=event_type,
            payload=payload,
        )))


def _merge_events(stored: ChildAgentRunRecord, fresh: ChildAgentRunRecord) -> ChildAgentRunRecord:
    known = {event.event_id for event in stored.events}
    new_events = tuple(event for event in fresh.events if event.event_id not in known)
    return replace(
        fresh,
        definition=stored.definition,
        events=(*stored.events, *new_events),
    )


def _unverified(artifact: AgentArtifact) -> AgentArtifact:
    return replace(artifact, producer_verification_status="unverified")


__all__ = ["AgentGateway", "InMemoryAgentRunStore"]
