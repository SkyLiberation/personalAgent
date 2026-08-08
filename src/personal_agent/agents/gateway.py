from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from hashlib import sha256
import json
from typing import Protocol

from personal_agent.governance.policy import PolicyEngine, PolicyInput
from personal_agent.capabilities.contracts.grants import DelegationGrant
from personal_agent.kernel.contracts.agent import (
    AgentAdapter,
    AgentArtifact,
    ChildAgentArtifactIndex,
    ChildAgentRunRecord,
    ChildAgentRunDefinition,
    ChildAgentRunProjection,
    ReservedAgentSubmission,
    SubagentProfile,
    ChildAgentRunEvent,
    AgentGatewayContext,
    ChildAgentRunOutcome,
    AgentTask,
    new_agent_event_id,
    new_agent_run_id,
)


class AgentSubmissionOutcomeUnknown(RuntimeError):
    """A reserved provider submission cannot be safely retried or reconciled."""


class AgentRunStorePort(Protocol):
    def reserve_submission(
        self,
        *,
        submission_key: str,
        definition_digest: str,
        definition: ChildAgentRunDefinition,
    ) -> ReservedAgentSubmission: ...

    def commit_submission(
        self,
        *,
        submission_key: str,
        definition_digest: str,
        run: ChildAgentRunRecord,
    ) -> ChildAgentRunRecord: ...

    def put(self, run: ChildAgentRunRecord) -> ChildAgentRunRecord: ...

    def get(self, agent_run_id: str) -> ChildAgentRunRecord | None: ...

    def get_by_submission_key(self, submission_key: str) -> ChildAgentRunRecord | None: ...

    def list(
        self,
        *,
        run_id: str | None = None,
        agent_id: str | None = None,
    ) -> tuple[ChildAgentRunRecord, ...]: ...


class InMemoryAgentRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, ChildAgentRunRecord] = {}
        self._submission_keys: dict[str, tuple[str, str]] = {}

    def reserve_submission(
        self,
        *,
        submission_key: str,
        definition_digest: str,
        definition: ChildAgentRunDefinition,
    ) -> ReservedAgentSubmission:
        existing = self._submission_keys.get(submission_key)
        if existing is not None:
            agent_run_id, existing_digest = existing
            if existing_digest != definition_digest:
                raise RuntimeError("submission_key is bound to a different definition")
            return ReservedAgentSubmission(self._runs[agent_run_id], created=False)
        run = ChildAgentRunRecord(
            definition=definition,
            projection=ChildAgentRunProjection(
                agent_run_id=definition.agent_run_id,
                status="created",
            ),
            artifact_index=ChildAgentArtifactIndex(agent_run_id=definition.agent_run_id),
        )
        self._runs[definition.agent_run_id] = run
        self._submission_keys[submission_key] = (
            definition.agent_run_id,
            definition_digest,
        )
        return ReservedAgentSubmission(run, created=True)

    def commit_submission(
        self,
        *,
        submission_key: str,
        definition_digest: str,
        run: ChildAgentRunRecord,
    ) -> ChildAgentRunRecord:
        reserved = self.reserve_submission(
            submission_key=submission_key,
            definition_digest=definition_digest,
            definition=run.definition,
        ).run
        canonical = replace(run, definition=reserved.definition)
        return self.put(canonical)

    def put(self, run: ChildAgentRunRecord) -> ChildAgentRunRecord:
        self._runs[run.definition.agent_run_id] = run
        return run

    def get(self, agent_run_id: str) -> ChildAgentRunRecord | None:
        return self._runs.get(agent_run_id)

    def get_by_submission_key(self, submission_key: str) -> ChildAgentRunRecord | None:
        binding = self._submission_keys.get(submission_key)
        return self._runs.get(binding[0]) if binding is not None else None

    def list(self, *, run_id: str | None = None, agent_id: str | None = None) -> tuple[ChildAgentRunRecord, ...]:
        runs = list(self._runs.values())
        if run_id is not None:
            runs = [
                run
                for run in runs
                if run.definition.context.execution_scope.execution_id == run_id
            ]
        if agent_id is not None:
            runs = [run for run in runs if run.definition.agent_id == agent_id]
        return tuple(runs)


class AgentGateway:
    def __init__(
        self,
        *,
        policy_engine: PolicyEngine,
        store: AgentRunStorePort,
    ) -> None:
        self._policy_engine = policy_engine
        self._store = store
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
        grant: DelegationGrant,
        *,
        submission_key: str,
    ) -> ChildAgentRunOutcome:
        self._authorize_grant(agent_id, context, grant)
        adapter = self._adapter(agent_id)
        self._authorize(adapter.profile, context, execution_mode="deterministic")
        definition = self._new_definition(
            agent_id=agent_id,
            task=task,
            context=context,
            grant=grant,
            submission_key=submission_key,
        )
        definition_digest = _definition_digest(definition)
        reservation = self._store.reserve_submission(
            submission_key=submission_key,
            definition_digest=definition_digest,
            definition=definition,
        )
        if not reservation.created:
            stored = reservation.run
            if stored.projection.status == "completed":
                return ChildAgentRunOutcome(
                    run=stored,
                    output_text=str(
                        stored.projection.result.get("_gateway_output_text", "")
                    ),
                    metadata=dict(
                        stored.projection.result.get("_gateway_metadata", {})
                    ),
                )
            raise AgentSubmissionOutcomeUnknown(
                "reserved synchronous child invocation has no committed result; "
                "retrying could duplicate provider work"
            )
        try:
            result = adapter.invoke(task, context)
        except Exception as exc:
            raise AgentSubmissionOutcomeUnknown(
                "synchronous child invocation outcome is unknown and cannot be retried"
            ) from exc
        canonical = _canonicalize_run(reservation.run, result.run)
        run = self._append_event(
            canonical,
            "completed",
            {"status": canonical.projection.status},
        )
        run = replace(
            run,
            projection=replace(
                run.projection,
                result={
                    **run.projection.result,
                    "_gateway_output_text": result.output_text,
                    "_gateway_metadata": result.metadata,
                },
            ),
            artifact_index=ChildAgentArtifactIndex(
                agent_run_id=run.definition.agent_run_id,
                artifacts=tuple(
                    _unverified(artifact) for artifact in run.artifact_index.artifacts
                ),
            ),
        )
        run = self._store.commit_submission(
            submission_key=submission_key,
            definition_digest=definition_digest,
            run=run,
        )
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
        grant: DelegationGrant,
        *,
        submission_key: str,
    ) -> ChildAgentRunRecord:
        self._authorize_grant(agent_id, context, grant)
        adapter = self._adapter(agent_id)
        self._authorize(adapter.profile, context, execution_mode="deterministic")
        definition = self._new_definition(
            agent_id=agent_id,
            task=task,
            context=context,
            submission_key=submission_key,
            grant=grant,
        )
        definition_digest = _definition_digest(definition)
        reservation = self._store.reserve_submission(
            submission_key=submission_key,
            definition_digest=definition_digest,
            definition=definition,
        )
        if not reservation.created:
            if reservation.run.projection.external_task_id:
                return reservation.run
            lookup = getattr(adapter, "lookup_submission", None)
            reconciled = (
                lookup(submission_key, task, context)
                if callable(lookup)
                else None
            )
            if reconciled is None:
                raise AgentSubmissionOutcomeUnknown(
                    "reserved child submission has no provider binding and the provider "
                    "cannot reconcile its stable submission key"
                )
            return self._commit_reconciled(
                reservation.run,
                reconciled,
                submission_key=submission_key,
                definition_digest=definition_digest,
            )
        try:
            submitted = adapter.submit(task, context, submission_key=submission_key)
        except Exception as exc:
            raise AgentSubmissionOutcomeUnknown(
                "provider submit outcome is unknown; retry requires lookup_submission"
            ) from exc
        return self._commit_reconciled(
            reservation.run,
            submitted,
            submission_key=submission_key,
            definition_digest=definition_digest,
        )

    def _commit_reconciled(
        self,
        reserved: ChildAgentRunRecord,
        submitted: ChildAgentRunRecord,
        *,
        submission_key: str,
        definition_digest: str,
    ) -> ChildAgentRunRecord:
        if not submitted.projection.external_task_id:
            raise AgentSubmissionOutcomeUnknown(
                "provider submission did not return a canonical provider task id"
            )
        run = _canonicalize_run(reserved, submitted)
        run = self._append_event(
            run,
            "submitted",
            {
                "status": run.projection.status,
                "submission_key": submission_key,
                "provider_task_id": run.projection.external_task_id,
            },
        )
        return self._store.commit_submission(
            submission_key=submission_key,
            definition_digest=definition_digest,
            run=run,
        )

    @staticmethod
    def _new_definition(
        *,
        agent_id: str,
        task: AgentTask,
        context: AgentGatewayContext,
        grant: DelegationGrant,
        submission_key: str,
    ) -> ChildAgentRunDefinition:
        return ChildAgentRunDefinition(
            agent_run_id=new_agent_run_id(),
            agent_id=agent_id,
            task=task,
            context=context,
            submission_key=submission_key,
            authorization_digest=grant.authorization_digest,
            execution_command_digest=grant.execution_command_digest,
        )

    def poll(self, agent_run_id: str, context: AgentGatewayContext) -> ChildAgentRunRecord:
        stored = self._require_run(agent_run_id)
        self._authorize_context(stored, context)
        adapter = self._adapter(stored.definition.agent_id)
        self._authorize(adapter.profile, context, execution_mode="deterministic")
        run = adapter.poll(stored, context)
        return self._store.put(_unverified_artifacts(_merge_events(stored, run)))

    def cancel(self, agent_run_id: str, context: AgentGatewayContext) -> ChildAgentRunRecord:
        stored = self._require_run(agent_run_id)
        self._authorize_context(stored, context)
        if stored.projection.status in {"cancelled", "completed", "completed_degraded"}:
            return stored
        adapter = self._adapter(stored.definition.agent_id)
        self._authorize(adapter.profile, context, execution_mode="deterministic")
        run = adapter.cancel(stored, context)
        run = self._append_event(
            _merge_events(stored, run), "cancelled", {"status": run.projection.status},
        )
        return self._store.put(run)

    def stream(self, agent_run_id: str, context: AgentGatewayContext) -> Iterator[ChildAgentRunEvent]:
        stored = self._require_run(agent_run_id)
        self._authorize_context(stored, context)
        adapter = self._adapter(stored.definition.agent_id)
        self._authorize(adapter.profile, context, execution_mode="deterministic")
        for event in adapter.stream(stored, context):
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

    @staticmethod
    def _authorize_context(run: ChildAgentRunRecord, context: AgentGatewayContext) -> None:
        owner = run.definition.context
        if owner.execution_scope != context.execution_scope:
            raise PermissionError("child agent run belongs to a different parent scope")

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
            user_id=context.execution_scope.principal.principal_id,
            session_id=context.execution_scope.principal.user_id,
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
    def _authorize_grant(
        agent_id: str,
        context: AgentGatewayContext,
        grant: DelegationGrant,
    ) -> None:
        if grant.agent_binding_ref.rsplit(":", 1)[-1] != agent_id:
            raise PermissionError("delegation grant is bound to a different agent")
        action_id = context.execution_scope.task_id
        if action_id and grant.action_ref != action_id:
            raise PermissionError("delegation grant is bound to a different child start")

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


def _canonicalize_run(
    reserved: ChildAgentRunRecord,
    returned: ChildAgentRunRecord,
) -> ChildAgentRunRecord:
    agent_run_id = reserved.definition.agent_run_id
    return replace(
        returned,
        definition=reserved.definition,
        projection=replace(
            returned.projection,
            agent_run_id=agent_run_id,
        ),
        artifact_index=replace(
            returned.artifact_index,
            agent_run_id=agent_run_id,
            artifacts=tuple(
                replace(artifact, agent_run_id=agent_run_id)
                for artifact in returned.artifact_index.artifacts
            ),
        ),
        events=tuple(
            replace(event, agent_run_id=agent_run_id)
            for event in returned.events
        ),
    )


def _unverified(artifact: AgentArtifact) -> AgentArtifact:
    return replace(artifact, producer_verification_status="unverified")


def _unverified_artifacts(run: ChildAgentRunRecord) -> ChildAgentRunRecord:
    return replace(run, artifact_index=ChildAgentArtifactIndex(
        agent_run_id=run.definition.agent_run_id,
        artifacts=tuple(_unverified(item) for item in run.artifact_index.artifacts),
    ))


def _definition_digest(definition: ChildAgentRunDefinition) -> str:
    payload = {
        "agent_id": definition.agent_id,
        "task": {
            "task_text": definition.task.task_text,
            "task_type": definition.task.task_type,
            "input": definition.task.input,
            "metadata": definition.task.metadata,
        },
        "context": {
            "execution_scope": definition.context.execution_scope.model_dump(
                mode="json"
            ),
            "source_platform": definition.context.source_platform,
        },
        "submission_key": definition.submission_key,
        "authorization_digest": definition.authorization_digest,
        "execution_command_digest": definition.execution_command_digest,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


__all__ = [
    "AgentGateway",
    "AgentRunStorePort",
    "AgentSubmissionOutcomeUnknown",
    "InMemoryAgentRunStore",
    "ReservedAgentSubmission",
]
