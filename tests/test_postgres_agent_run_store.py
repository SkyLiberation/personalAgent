from __future__ import annotations

from personal_agent.agents import AgentGateway
from personal_agent.agents.gateway import AgentSubmissionOutcomeUnknown
from personal_agent.capabilities.contracts.grants import (
    DelegationGrant,
    GrantDependencySet,
)
from personal_agent.governance.policy import PolicyEngine
from personal_agent.infra.storage.postgres_agent_run_store import (
    PostgresAgentRunStore,
)
from personal_agent.kernel.contracts.agent import (
    AgentGatewayContext,
    AgentGovernance,
    AgentTask,
    ChildAgentArtifactIndex,
    ChildAgentRunDefinition,
    ChildAgentRunProjection,
    ChildAgentRunRecord,
    SubagentProfile,
    new_agent_run_id,
)
from personal_agent.kernel.contracts.resource import OperationScope, ResourceSelector
from personal_agent.kernel.contracts.scope import interaction_execution_scope


def test_reserved_agent_submission_reconciles_after_gateway_restart(
    postgres_url,
    clean_postgres_business_tables,
):
    provider = _OutcomeUnknownProvider()
    context = AgentGatewayContext(
        execution_scope=interaction_execution_scope(
            tenant_id="tenant-1",
            user_id="alice",
            execution_id="project-1",
            task_id="subgoal-1",
        ),
    )
    first = AgentGateway(
        policy_engine=PolicyEngine(),
        store=PostgresAgentRunStore(postgres_url),
    )
    first.register(provider)

    try:
        first.submit(
            "researcher",
            AgentTask("bounded investigation"),
            context,
            _grant(),
            submission_key="stable-submission-key",
        )
    except AgentSubmissionOutcomeUnknown:
        pass
    else:
        raise AssertionError("the injected uncertain provider result must fail closed")

    restarted = AgentGateway(
        policy_engine=PolicyEngine(),
        store=PostgresAgentRunStore(postgres_url),
    )
    restarted.register(provider)
    reconciled = restarted.submit(
        "researcher",
        AgentTask("bounded investigation"),
        context,
        _grant(),
        submission_key="stable-submission-key",
    )

    assert provider.submit_count == 1
    assert provider.lookup_count == 1
    assert reconciled.projection.external_task_id == "provider-task-1"
    assert restarted.get_run(reconciled.definition.agent_run_id) is not None


class _OutcomeUnknownProvider:
    profile = SubagentProfile(
        agent_id="researcher",
        provider="test",
        protocol="local",
        governance=AgentGovernance(permission_scope="agent:invoke"),
    )

    def __init__(self) -> None:
        self.submit_count = 0
        self.lookup_count = 0
        self._submitted: dict[str, ChildAgentRunRecord] = {}

    def invoke(self, task, context):
        raise AssertionError("durable child execution must use submit/reconcile")

    def submit(
        self,
        task: AgentTask,
        context: AgentGatewayContext,
        *,
        submission_key: str,
    ) -> ChildAgentRunRecord:
        self.submit_count += 1
        run = _provider_run(task, context)
        self._submitted[submission_key] = run
        raise ConnectionError("response lost after provider accepted submission")

    def lookup_submission(
        self,
        submission_key: str,
        task: AgentTask,
        context: AgentGatewayContext,
    ) -> ChildAgentRunRecord | None:
        self.lookup_count += 1
        return self._submitted.get(submission_key)

    def poll(self, run, context):
        return run

    def cancel(self, run, context):
        return run

    def stream(self, run, context):
        return iter(())


def _provider_run(
    task: AgentTask,
    context: AgentGatewayContext,
) -> ChildAgentRunRecord:
    run_id = new_agent_run_id()
    return ChildAgentRunRecord(
        definition=ChildAgentRunDefinition(
            agent_run_id=run_id,
            agent_id="researcher",
            task=task,
            context=context,
        ),
        projection=ChildAgentRunProjection(
            agent_run_id=run_id,
            status="running",
            external_task_id="provider-task-1",
        ),
        artifact_index=ChildAgentArtifactIndex(agent_run_id=run_id),
    )


def _grant() -> DelegationGrant:
    return DelegationGrant(
        request_id="request-1",
        action_ref="subgoal-1",
        authorization_digest="authorization-digest",
        execution_command_digest="execution-command-digest",
        granted_resource_selector=ResourceSelector(),
        granted_operation_scope=OperationScope(
            operations=frozenset({"delegate"})
        ),
        granted_data_egress="content",
        granted_credential_mode="none",
        retry_family_id="retry-1",
        dependency_set=GrantDependencySet(
            task_revision=1,
            goal_definition_fingerprint="goal",
            action_fingerprint="subgoal-1",
            capability_definition_revision=1,
            authority_revision=1,
            policy_bundle_hash="policy",
        ),
        agent_binding_ref="local:researcher",
        bounded_sub_goal="bounded investigation",
        token_budget=1000,
        cost_budget=1,
        time_budget_seconds=60,
        completion_contract="AgentArtifact",
    )
