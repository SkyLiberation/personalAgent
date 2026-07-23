from __future__ import annotations

from types import SimpleNamespace

import pytest

from personal_agent.agents.runtime import SubagentRuntime
from personal_agent.context.projection import (
    ContextManager,
    ContextRequirement,
    ContextSelectionProposal,
    ContextSelectionRequired,
)
from personal_agent.kernel.contracts.agent import (
    AgentArtifact,
    AgentGatewayContext,
    ChildAgentArtifactIndex,
    ChildAgentRunDefinition,
    ChildAgentRunProjection,
    ChildAgentRunRecord,
    AgentTask,
    SubagentProfile,
)
from personal_agent.runtime.contracts.task import (
    ContextBudget,
    ContextItem,
    RuntimeSnapshotRef,
    TaskRuntimeProjection,
)
from personal_agent.capabilities.contracts.execution import CapabilityRequirement
from personal_agent.capabilities.contracts.grants import DelegationGrant, GrantDependencySet
from personal_agent.kernel.contracts.resource import OperationScope, ResourceSelector
from personal_agent.execution.contracts.invocation import InvocationAttemptState
from personal_agent.runtime.contracts.control import (
    BoundedAction,
    CapabilityActionInput,
    ProposedResourceAccessPlan,
    ResourceAccess,
    SubtaskSpec,
)
from personal_agent.runtime.recovery import ObservationNormalizer, TechnicalRecoveryPolicy
from personal_agent.runtime.action_spec import ResolvedActionBuilder
from personal_agent.runtime.resource_access import (
    ResourceAccessResolutionError,
    ResourceAccessResolver,
)
from personal_agent.runtime.run_manager import DurableRunManager, RunStateError
from personal_agent.runtime.scheduler import RunScheduler
from personal_agent.skills.registry import SkillRegistry
from personal_agent.orchestration.orchestration_models import (
    RunCheckpoint,
    InvocationBatchState,
    ExecutableInvocation,
)
from personal_agent.orchestration.entry_orchestrator import _admit_terminal_run
from personal_agent.orchestration.orchestration_nodes._steps import (
    _execute_agent_call_step,
    _node_select_next_step,
)


def test_open_context_requires_model_selection_and_respects_budget() -> None:
    items = (
        ContextItem(
                item_id="untrusted",
                category="observation",
            kind="web",
            provenance="web",
                trust="untrusted",
            summary="x" * 200,
            payload={"authority_tier": "untrusted_content"},
        ),
        ContextItem(
                item_id="policy",
                category="run",
            kind="policy",
            provenance="runtime",
                trust="runtime",
            summary="required policy",
            payload={"authority_tier": "system_policy"},
        ),
    )
    requirement = ContextRequirement(
        purpose="executive_decision",
        semantic_query="select policy and relevant observations",
    )
    manager = ContextManager()
    budget = ContextBudget(
        model_profile="test",
        tokenizer_profile="test",
        max_context_tokens=40,
        safety_margin=5,
        reserved_output_tokens=10,
    )
    snapshot = RuntimeSnapshotRef(
        run_id="run", task_id="task", task_revision=1,
        runtime_revision=3, event_sequence=7,
    )

    with pytest.raises(ContextSelectionRequired):
        manager.project(
            items,
            requirement=requirement,
            selection=None,
            budget=budget,
            source_snapshot=snapshot,
        )

    projection = manager.project(
        items,
        requirement=requirement,
        selection=ContextSelectionProposal(
            requirement_ref=requirement.requirement_id,
            source="model",
            required_item_ids=("policy",),
            optional_item_ids=("untrusted",),
            optional_priority=("untrusted",),
        ),
        budget=budget,
        source_snapshot=snapshot,
    )

    assert projection.selected_item_ids == ("policy",)
    assert tuple(item.item_id for item in projection.omitted) == ("untrusted",)
    assert projection.token_estimate <= 25


def test_resource_resolution_rejects_silent_scope_expansion() -> None:
    resolver = ResourceAccessResolver()
    proposed = ProposedResourceAccessPlan(
        read_set=(ResourceAccess(semantic_domain="knowledge", locator="note:1"),),
        side_effect_class="none",
        authority_scope="memory:read",
        data_egress_class="none",
        trust_floor="trusted",
        freshness_contract="current_snapshot",
        evidence_contract="resource_read",
        failure_semantics="return_typed_failure",
    )
    authoritative = ProposedResourceAccessPlan(
        write_set=(ResourceAccess(semantic_domain="knowledge", locator="note:1"),),
        side_effect_class="mutation",
        authority_scope="memory:write",
        data_egress_class="none",
        trust_floor="trusted",
        freshness_contract="current_snapshot",
        evidence_contract="mutation_receipt",
        failure_semantics="return_typed_failure",
    )
    with pytest.raises(ResourceAccessResolutionError, match="undeclared write access"):
        resolver.resolve(
            proposed,
            procedure_contract=authoritative,
            runtime_preflight=authoritative,
        )


def test_resource_resolution_preserves_proposal_and_scheduler_is_physical_only() -> None:
    resolver = ResourceAccessResolver()
    proposed = ProposedResourceAccessPlan(
        read_set=(ResourceAccess(semantic_domain="knowledge", locator="note:1"),),
        write_set=(ResourceAccess(semantic_domain="knowledge", locator="note:1"),),
        side_effect_class="mutation",
        authority_scope="memory:write",
        data_egress_class="none",
        trust_floor="trusted",
        freshness_contract="current_snapshot",
        evidence_contract="mutation_receipt",
        failure_semantics="return_typed_failure",
    )
    resolved = resolver.resolve(
        proposed,
        procedure_contract=proposed,
        runtime_preflight=proposed,
    )
    spec = ResolvedActionBuilder().build(
        decision_ref="decision",
        action=BoundedAction(
            action_id="action",
            goal_id="goal",
            execution_intent="commit",
            description="update note",
            proposed_resource_access=proposed,
            input=CapabilityActionInput(task_text="update note:1"),
        ),
        context_projection_ref="projection",
        access_plan=resolved,
    )

    RunScheduler().validate_dispatch(spec)
    assert resolved.read_set == proposed.read_set
    assert resolved.write_set == proposed.write_set
    assert resolved.source_refs[0] == "procedure_contract"


def test_technical_recovery_excludes_provider_without_selecting_replacement() -> None:
    observation = ObservationNormalizer().normalize(
        goal_id="goal",
        provenance="provider-a",
        summary="503 temporarily unavailable",
    )
    directive = TechnicalRecoveryPolicy().directive(
        observation,
        requirement_id="requirement",
        idempotency_key="retry-key",
        attempt_count=1,
        max_attempts=3,
        action_idempotent=True,
        failed_provider_id="provider-a",
    )

    assert directive.retry_kind == "equivalent_provider"
    assert directive.excluded_provider_ids == ("provider-a",)
    assert not hasattr(directive, "selected_provider_id")


def test_builtin_skill_requires_installation_and_trust() -> None:
    untrusted = SkillRegistry()
    skill_id = untrusted.manifests()[0].skill_id
    with pytest.raises(PermissionError):
        untrusted.get("tenant", skill_id)

    trusted = SkillRegistry.with_builtin_trust("tenant")
    loaded = trusted.get("tenant", skill_id)
    assert loaded.instructions
    assert loaded.manifest.skill_id == skill_id


def test_subagent_scope_is_strict_intersection_and_budget_is_parent_owned() -> None:
    runtime = SubagentRuntime()
    profile = SubagentProfile(
        agent_id="researcher",
        provider="local",
        protocol="local",
        capability_ids=("agent:researcher", "tool:web"),
        allowed_operations=("delegate", "read"),
    )
    requirement = CapabilityRequirement.from_dimensions(
        requirement_id="delegate",
        purpose="research",
        operations=("delegate",),
    )
    subtask = SubtaskSpec(
        goal="research",
        parent_goal_id="goal",
        required_capability=requirement,
        requested_capability_ids=("agent:researcher", "tool:web"),
        requested_operations=("delegate",),
        token_budget=100,
        cost_budget=0.5,
        time_budget_seconds=30,
    )
    scope = runtime.effective_scope(
        profile=profile,
        parent_capability_ids=("agent:researcher",),
        parent_operations=("delegate",),
        policy_capability_ids=("agent:researcher", "tool:web"),
        policy_operations=("delegate",),
        subtask=subtask,
    )
    reservation = runtime.reserve(
        parent_run_id="parent",
        child_run_id="child",
        subtask=subtask,
        parent_token_remaining=100,
        parent_cost_remaining=0.5,
        parent_time_remaining=30,
    )

    assert scope.capability_ids == ("agent:researcher",)
    assert scope.operations == ("delegate",)
    assert reservation.child_run_id == "child"


def test_run_manager_fences_old_worker_and_quarantines_cancel_race() -> None:
    manager = DurableRunManager()
    first = manager.submit("run", idempotency_key="submit")
    assert manager.submit("run", idempotency_key="submit") is first
    old_lease = manager.acquire_lease("run")
    manager.transition("run", "queued", fencing_token=old_lease.fencing_token)
    new_lease = manager.acquire_lease("run")
    with pytest.raises(RunStateError, match="stale fencing"):
        manager.transition("run", "running", fencing_token=old_lease.fencing_token)

    manager.transition("run", "running", fencing_token=new_lease.fencing_token)
    manager.request_cancel("run", fencing_token=new_lease.fencing_token)
    completed = manager.admit_external_completion(
        "run",
        fencing_token=new_lease.fencing_token,
        artifact_refs=("artifact:late",),
    )
    assert completed.status == "cancelled"
    assert completed.orphan_artifact_refs == ("artifact:late",)


def test_run_manager_renews_only_the_current_lease_identity() -> None:
    manager = DurableRunManager()
    manager.submit("renew-run", idempotency_key="renew-submit")
    first = manager.acquire_lease("renew-run", ttl_seconds=1)
    renewed = manager.renew_lease("renew-run", first, ttl_seconds=60)

    assert renewed.lease_id == first.lease_id
    assert renewed.fencing_token == first.fencing_token
    assert renewed.expires_at > first.expires_at

    current = manager.acquire_lease("renew-run")
    with pytest.raises(RunStateError, match="stale fencing"):
        manager.renew_lease("renew-run", first)
    assert manager.renew_lease("renew-run", current).lease_id == current.lease_id


@pytest.mark.parametrize(
    ("lifecycle", "errors", "expected_status"),
    [
        ("active", [], "failed"),
        ("terminated", [], "completed_degraded"),
        ("completed", [], "completed"),
        ("completed", ["completion rejected"], "failed"),
    ],
)
def test_graph_return_does_not_fabricate_run_completion(
    lifecycle: str,
    errors: list[str],
    expected_status: str,
) -> None:
    manager = DurableRunManager()
    manager.submit("terminal-run", idempotency_key="terminal-submit")
    lease = manager.acquire_lease("terminal-run")
    manager.transition("terminal-run", "queued", fencing_token=lease.fencing_token)
    manager.transition("terminal-run", "running", fencing_token=lease.fencing_token)
    state = RunCheckpoint(
        task_runtime=TaskRuntimeProjection(
            task_id="task",
            lifecycle=lifecycle,
            termination_reason=(
                "unrecoverable_failure" if lifecycle == "terminated" else None
            ),
        ),
        errors=errors,
    )

    result = _admit_terminal_run(manager, "terminal-run", state)

    assert result.status == expected_status


def test_agent_step_uses_durable_submit_then_poll() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def submit(
            self,
            agent_id: str,
            task: AgentTask,
            context: AgentGatewayContext,
            grant: DelegationGrant,
        ) -> ChildAgentRunRecord:
            self.calls.append("submit")
            return ChildAgentRunRecord(
                definition=ChildAgentRunDefinition(
                    agent_run_id="child-1", agent_id=agent_id, task=task, context=context,
                ),
                projection=ChildAgentRunProjection(
                    agent_run_id="child-1", status="running",
                ),
                artifact_index=ChildAgentArtifactIndex(agent_run_id="child-1"),
            )

        def poll(self, agent_run_id: str, context: AgentGatewayContext) -> ChildAgentRunRecord:
            self.calls.append("poll")
            artifact = AgentArtifact(
                artifact_id="artifact-1",
                agent_run_id=agent_run_id,
                kind="report",
                content="verified later by parent",
            )
            return ChildAgentRunRecord(
                definition=ChildAgentRunDefinition(
                    agent_run_id=agent_run_id,
                    agent_id="researcher",
                    task=AgentTask("research"),
                    context=context,
                ),
                projection=ChildAgentRunProjection(
                    agent_run_id=agent_run_id,
                    status="completed",
                    result={"report": artifact.content},
                ),
                artifact_index=ChildAgentArtifactIndex(
                    agent_run_id=agent_run_id, artifacts=(artifact,),
                ),
            )

    class ArtifactStore:
        def put_artifact(self, **_kwargs) -> None:
            return None

    gateway = Gateway()
    deps = SimpleNamespace(
        agent_gateway=gateway,
        execution_artifact_store=ArtifactStore(),
    )
    step = ExecutableInvocation(
        step_id="delegate-1",
        action_type="agent_call",
        description="delegate research",
        agent_id="researcher",
        task_id="goal-1",
        task_input="research topic",
        execution_grant_ref="grant-delegate-1",
        attempt=InvocationAttemptState(status="running"),
    )
    grant = DelegationGrant(
        grant_id="grant-delegate-1",
        request_id="request-delegate-1",
        action_ref="delegate-1",
        authorization_digest="authorization-digest",
        execution_command_digest="execution-command-digest",
        granted_resource_selector=ResourceSelector(),
        granted_operation_scope=OperationScope(operations=frozenset({"delegate"})),
        granted_data_egress="content",
        granted_credential_mode="none",
        retry_family_id="retry-delegate-1",
        dependency_set=GrantDependencySet(
            task_revision=1,
            goal_definition_fingerprint="goal",
            action_fingerprint="action",
            capability_definition_revision=1,
            authority_revision=1,
            policy_bundle_hash="policy",
        ),
        agent_binding_ref="local:researcher",
        bounded_sub_goal="research topic",
        token_budget=1024,
        cost_budget=1,
        time_budget_seconds=60,
        completion_contract="AgentArtifact",
    )
    state = RunCheckpoint(
        run_id="parent-1",
        user_id="tenant",
        session_id="session",
        invocation_batch=InvocationBatchState(invocations=[step]),
        execution_grants={grant.grant_id: grant},
    )

    assert not _execute_agent_call_step(step, step, state, deps)
    assert gateway.calls == ["submit"]
    assert state.invocation_batch.results[step.step_id]["status"] == "running"

    assert _execute_agent_call_step(step, step, state, deps)
    assert gateway.calls == ["submit", "poll"]
    assert state.invocation_batch.results[step.step_id]["report"] == "verified later by parent"
    assert state.context_inventory.selected(category="observation")[0].item_id == "agent:artifact-1"


def test_submitted_child_polling_is_round_robin() -> None:
    state = RunCheckpoint(
        invocation_batch=InvocationBatchState(
            invocations=[
                ExecutableInvocation(
                    step_id="child-a", action_type="agent_call", description="child a",
                    attempt=InvocationAttemptState(status="submitted"),
                ),
                ExecutableInvocation(
                    step_id="child-b", action_type="agent_call", description="child b",
                    attempt=InvocationAttemptState(status="submitted"),
                ),
            ],
            current_step_index=0,
        ),
    )

    _node_select_next_step(state)
    assert state.invocation_batch.current_step_index == 1
    state.invocation_batch.invocations[1].status = "submitted"
    _node_select_next_step(state)
    assert state.invocation_batch.current_step_index == 0
