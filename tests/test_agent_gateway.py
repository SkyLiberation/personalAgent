from __future__ import annotations

import pytest

from personal_agent.agents import (
    AgentCapacityUnavailable,
    AgentGateway,
    InMemoryAgentRunStore,
)
from personal_agent.governance.policy import PolicyEngine
from personal_agent.capabilities.contracts.grants import DelegationGrant, GrantDependencySet
from personal_agent.kernel.contracts.resource import (
    OperationScope,
    ResourceRef,
    ResourceSelector,
)
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
from personal_agent.kernel.contracts.scope import (
    AuthenticatedPrincipal,
    interaction_execution_scope,
)


def test_agent_gateway_invoke_records_unverified_artifact():
    gateway = AgentGateway(
        policy_engine=PolicyEngine(), store=InMemoryAgentRunStore()
    )
    gateway.register(_FakeAgent("researcher", output="report"))

    result = gateway.invoke(
        "researcher",
        AgentTask("topic"),
        _ctx(),
        _grant("researcher"),
        submission_key="invoke-researcher",
    )

    assert result.run.projection.status == "completed"
    assert result.run.definition.agent_id == "researcher"
    assert result.run.artifact_index.artifacts[0].producer_verification_status == "unverified"
    assert gateway.get_run(result.run.definition.agent_run_id) is not None


def test_agent_gateway_invoke_reuses_committed_submission_without_duplicate_call():
    gateway = AgentGateway(
        policy_engine=PolicyEngine(), store=InMemoryAgentRunStore()
    )
    adapter = _FakeAgent("researcher", output="report")
    gateway.register(adapter)

    first = gateway.invoke(
        "researcher",
        AgentTask("topic"),
        _ctx(),
        _grant("researcher"),
        submission_key="invoke-idempotent",
    )
    second = gateway.invoke(
        "researcher",
        AgentTask("topic"),
        _ctx(),
        _grant("researcher"),
        submission_key="invoke-idempotent",
    )

    assert second.run.definition.agent_run_id == first.run.definition.agent_run_id
    assert second.output_text == "report"
    assert adapter.invoke_count == 1


def test_agent_gateway_submit_poll_cancel_and_stream():
    gateway = AgentGateway(
        policy_engine=PolicyEngine(), store=InMemoryAgentRunStore()
    )
    gateway.register(_FakeAgent("researcher", output="report"))

    submitted = gateway.submit(
        "researcher",
        AgentTask("topic"),
        _ctx(),
        _grant("researcher"),
        submission_key="submission-1",
    )
    assert submitted.projection.status == "running"

    polled = gateway.poll(submitted.definition.agent_run_id, _ctx())
    assert polled.projection.status == "completed"

    stream = list(gateway.stream(submitted.definition.agent_run_id, _ctx()))
    assert [event.type for event in stream] == ["stream_delta"]

    canceled = gateway.cancel(submitted.definition.agent_run_id, _ctx())
    assert canceled.projection.status == "completed"

    cancellable = gateway.submit(
        "researcher",
        AgentTask("another topic"),
        _ctx(),
        _grant("researcher"),
        submission_key="submission-2",
    )
    canceled = gateway.cancel(cancellable.definition.agent_run_id, _ctx())
    assert canceled.projection.status == "cancelled"
    assert gateway.cancel(cancellable.definition.agent_run_id, _ctx()) == canceled


def test_agent_gateway_records_budget_expiry_as_timeout_not_user_cancellation():
    gateway = AgentGateway(
        policy_engine=PolicyEngine(), store=InMemoryAgentRunStore()
    )
    gateway.register(_FakeAgent("researcher", output="partial report"))
    submitted = gateway.submit(
        "researcher",
        AgentTask("topic"),
        _ctx(),
        _grant("researcher"),
        submission_key="timeout-1",
    )

    timed_out = gateway.timeout(submitted.definition.agent_run_id, _ctx())

    assert timed_out.projection.status == "timed_out"
    assert timed_out.projection.error == (
        "child Agent exceeded its delegated time budget"
    )
    assert timed_out.events[-1].type == "timed_out"


def test_agent_gateway_admits_new_async_runs_only_when_provider_slot_exists():
    gateway = AgentGateway(
        policy_engine=PolicyEngine(), store=InMemoryAgentRunStore()
    )
    adapter = _FakeAgent(
        "researcher",
        output="report",
        max_concurrent_runs=2,
    )
    gateway.register(adapter)

    first = gateway.submit(
        "researcher",
        AgentTask("topic one"),
        _ctx(),
        _grant("researcher"),
        submission_key="capacity-1",
    )
    gateway.submit(
        "researcher",
        AgentTask("topic two"),
        _ctx(),
        _grant("researcher"),
        submission_key="capacity-2",
    )

    same_first = gateway.submit(
        "researcher",
        AgentTask("topic one"),
        _ctx(),
        _grant("researcher"),
        submission_key="capacity-1",
    )
    assert same_first.definition.agent_run_id == first.definition.agent_run_id
    with pytest.raises(AgentCapacityUnavailable):
        gateway.submit(
            "researcher",
            AgentTask("topic three"),
            _ctx(),
            _grant("researcher"),
            submission_key="capacity-3",
        )
    assert adapter.submit_count == 2
    assert len(gateway.list_runs(agent_id="researcher")) == 2

    gateway.poll(first.definition.agent_run_id, _ctx())
    third = gateway.submit(
        "researcher",
        AgentTask("topic three"),
        _ctx(),
        _grant("researcher"),
        submission_key="capacity-3",
    )
    assert third.projection.status == "running"
    assert adapter.submit_count == 3


def test_agent_governance_rejects_a_non_positive_run_capacity():
    with pytest.raises(ValueError, match="max_concurrent_runs"):
        AgentGovernance(max_concurrent_runs=0)


def test_agent_gateway_keeps_multiple_agent_definitions_separate():
    gateway = AgentGateway(
        policy_engine=PolicyEngine(), store=InMemoryAgentRunStore()
    )
    gateway.register(_FakeAgent("researcher", output="research"))
    gateway.register(_FakeAgent("writer", output="write"))

    assert {item.agent_id for item in gateway.profiles()} == {"researcher", "writer"}
    result = gateway.invoke(
        "writer",
        AgentTask("draft"),
        _ctx(),
        _grant("writer"),
        submission_key="invoke-writer",
    )

    assert result.run.definition.agent_id == "writer"
    assert result.output_text == "write"


def test_agent_gateway_rejects_grant_above_registered_runtime_limit():
    gateway = AgentGateway(
        policy_engine=PolicyEngine(), store=InMemoryAgentRunStore()
    )
    adapter = _FakeAgent("researcher", output="research")
    gateway.register(adapter)
    oversized = _grant("researcher").model_copy(update={
        "time_budget_seconds": adapter.profile.max_runtime_seconds + 1,
    })

    with pytest.raises(
        PermissionError,
        match="delegation time budget exceeds agent runtime limit",
    ):
        gateway.invoke(
            "researcher",
            AgentTask("research"),
            _ctx(),
            oversized,
            submission_key="oversized-runtime-grant",
        )

    assert adapter.invoke_count == 0


def _ctx() -> AgentGatewayContext:
    return AgentGatewayContext(
        execution_scope=interaction_execution_scope(
            tenant_id="tenant-1",
            user_id="u1",
            execution_id="entry-run-1",
            task_id="action",
        ),
        source_platform="test",
    )


def _grant(agent_id: str) -> DelegationGrant:
    return DelegationGrant(
        request_id=f"request-{agent_id}",
        action_ref="action",
        granted_resource_selector=ResourceSelector(),
        granted_operation_scope=OperationScope(operations=frozenset({"delegate"})),
        granted_data_egress="content",
        granted_credential_mode="none",
        retry_family_id="retry-action",
        dependency_set=GrantDependencySet(
            task_revision=1,
            goal_definition_fingerprint="goal",
            action_fingerprint="action",
            capability_definition_revision=1,
            authority_revision=1,
            policy_bundle_hash="policy",
        ),
        agent_binding_ref=f"local:{agent_id}",
        bounded_sub_goal="bounded child task",
        token_budget=1024,
        cost_budget=1,
        time_budget_seconds=60,
        completion_contract="AgentArtifact",
        authorization_digest="authorization-digest",
        execution_command_digest="execution-command-digest",
    )


class _FakeAgent:
    def __init__(
        self,
        agent_id: str,
        *,
        output: str,
        max_concurrent_runs: int | None = None,
    ) -> None:
        self.profile = SubagentProfile(
            agent_id=agent_id,
            provider=agent_id,
            protocol="local",
            task_types=("research",),
            governance=AgentGovernance(
                permission_scope=f"a2a:{agent_id}:invoke",
                max_concurrent_runs=max_concurrent_runs,
            ),
        )
        self._output = output
        self.invoke_count = 0
        self.submit_count = 0

    def invoke(self, task: AgentTask, context: AgentGatewayContext) -> ChildAgentRunOutcome:
        self.invoke_count += 1
        run = self._run(task, context, status="completed")
        return ChildAgentRunOutcome(run=run, output_text=self._output)

    def submit(
        self,
        task: AgentTask,
        context: AgentGatewayContext,
        *,
        submission_key: str,
    ) -> ChildAgentRunRecord:
        self.submit_count += 1
        return self._run(task, context, status="running")

    def lookup_submission(
        self,
        submission_key: str,
        task: AgentTask,
        context: AgentGatewayContext,
    ) -> ChildAgentRunRecord | None:
        return None

    def poll(self, run: ChildAgentRunRecord, context: AgentGatewayContext) -> ChildAgentRunRecord:
        return self._run(run.definition.task, context, status="completed", agent_run_id=run.definition.agent_run_id)

    def cancel(self, run: ChildAgentRunRecord, context: AgentGatewayContext) -> ChildAgentRunRecord:
        return self._run(run.definition.task, context, status="cancelled", agent_run_id=run.definition.agent_run_id)

    def stream(self, run: ChildAgentRunRecord, context: AgentGatewayContext):
        yield ChildAgentRunEvent(
            event_id=new_agent_event_id(),
            agent_run_id=run.definition.agent_run_id,
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
            agent_run_id=run_id,
            kind="markdown_report",
            artifact_ref=ResourceRef(
                resource_id=f"artifact-{run_id}",
                resource_type="artifact",
                owner=AuthenticatedPrincipal(
                    tenant_id="tenant-1",
                    user_id="u1",
                ),
            ),
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
