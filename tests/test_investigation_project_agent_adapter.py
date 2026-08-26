from __future__ import annotations

import hashlib

import pytest

from personal_agent.agents.gateway import AgentCapacityUnavailable
from personal_agent.application.artifacts import ArtifactService
from personal_agent.application.investigation_project.ports import (
    ProjectAgentCapacityUnavailable,
    ProjectAgentExecutionFailed,
)
from personal_agent.domain.investigation_project import (
    AgentExecutionOperation,
    SubGoalExecutionProposal,
    canonical_digest,
)
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.agent import (
    AgentArtifact,
    AgentGatewayContext,
    AgentTask,
    ChildAgentArtifactIndex,
    ChildAgentRunDefinition,
    ChildAgentRunProjection,
    ChildAgentRunRecord,
)
from personal_agent.kernel.contracts.scope import (
    AuthenticatedPrincipal,
    ExecutionScope,
)
from personal_agent.orchestration.investigation_project_adapters import (
    DurableProjectAgentAdapter,
)


class _CompletedGateway:
    def __init__(self, run: ChildAgentRunRecord) -> None:
        self._run = run

    def submit(self, *args, **kwargs) -> ChildAgentRunRecord:
        return self._run


class _CapacityGateway:
    def submit(self, *args, **kwargs) -> ChildAgentRunRecord:
        raise AgentCapacityUnavailable("provider execution slots exhausted")


class _FailedGateway:
    def __init__(self, run: ChildAgentRunRecord) -> None:
        self._run = run

    def submit(self, *args, **kwargs) -> ChildAgentRunRecord:
        return self._run


def test_agent_capacity_exhaustion_is_a_retryable_project_runtime_outcome(
    temp_dir,
) -> None:
    principal = AuthenticatedPrincipal(tenant_id="tenant-1", user_id="user-1")
    execution_scope = ExecutionScope(
        principal=principal,
        execution_id="execution-agent-capacity",
        project_id="project-capacity",
        plan_version=1,
        logical_subgoal_id="research",
        subgoal_version=1,
    )
    proposal = SubGoalExecutionProposal(
        project_id="project-capacity",
        plan_version=1,
        logical_subgoal_id="research",
        subgoal_version=1,
        based_on_event_sequence=1,
        proposal_id="proposal-agent-capacity",
        operation=AgentExecutionOperation(
            agent_id="researcher",
            bounded_sub_goal="Research the bounded topic.",
            expected_artifact_types=("markdown_report",),
            token_budget=1_000,
            cost_budget=1,
            time_budget_seconds=60,
        ),
        proposal_digest=canonical_digest({"proposal": "agent-capacity"}),
    )

    with pytest.raises(ProjectAgentCapacityUnavailable):
        DurableProjectAgentAdapter(
            _CapacityGateway(),
            ArtifactService(Settings(data_dir=temp_dir)),
        ).submit_or_reconcile(
            proposal,
            execution_scope=execution_scope,
            submission_key="submission-agent-capacity",
        )


def test_terminal_child_agent_failure_is_a_typed_project_runtime_outcome(
    temp_dir,
) -> None:
    principal = AuthenticatedPrincipal(tenant_id="tenant-1", user_id="user-1")
    execution_scope = ExecutionScope(
        principal=principal,
        execution_id="execution-agent-failed",
        project_id="project-failed",
        plan_version=1,
        logical_subgoal_id="research",
        subgoal_version=1,
    )
    gateway_context = AgentGatewayContext(
        execution_scope=execution_scope,
        source_platform="investigation_project",
    )
    run = ChildAgentRunRecord(
        definition=ChildAgentRunDefinition(
            agent_run_id="agent-run-failed",
            agent_id="researcher",
            task=AgentTask(task_text="Research the bounded topic."),
            context=gateway_context,
        ),
        projection=ChildAgentRunProjection(
            agent_run_id="agent-run-failed",
            status="failed",
            error="provider research failed",
        ),
        artifact_index=ChildAgentArtifactIndex(
            agent_run_id="agent-run-failed",
        ),
    )
    proposal = SubGoalExecutionProposal(
        project_id="project-failed",
        plan_version=1,
        logical_subgoal_id="research",
        subgoal_version=1,
        based_on_event_sequence=1,
        proposal_id="proposal-agent-failed",
        operation=AgentExecutionOperation(
            agent_id="researcher",
            bounded_sub_goal="Research the bounded topic.",
            expected_artifact_types=("markdown_report",),
            token_budget=1_000,
            cost_budget=1,
            time_budget_seconds=60,
        ),
        proposal_digest=canonical_digest({"proposal": "agent-failed"}),
    )

    with pytest.raises(ProjectAgentExecutionFailed) as raised:
        DurableProjectAgentAdapter(
            _FailedGateway(run),
            ArtifactService(Settings(data_dir=temp_dir)),
        ).submit_or_reconcile(
            proposal,
            execution_scope=execution_scope,
            submission_key="submission-agent-failed",
        )

    assert raised.value.agent_run_id == "agent-run-failed"
    assert raised.value.status == "failed"
    assert raised.value.execution_ref.execution_id == "agent-run-failed"
    assert str(raised.value) == "provider research failed"


def test_agent_evidence_uses_the_canonical_stored_content_digest(temp_dir) -> None:
    principal = AuthenticatedPrincipal(tenant_id="tenant-1", user_id="user-1")
    execution_scope = ExecutionScope(
        principal=principal,
        execution_id="execution-agent-1",
        project_id="project-1",
        plan_version=1,
        logical_subgoal_id="research",
        subgoal_version=1,
    )
    artifacts = ArtifactService(Settings(data_dir=temp_dir))
    content = "A child-Agent report backed by official sources."
    stored_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    artifact_ref = artifacts.write_generated(
        owner=principal,
        execution_scope=execution_scope,
        producer_key="child-agent:research:1",
        producer_ref="agent-run-1",
        kind="markdown_report",
        content=content,
        content_digest=stored_digest,
        source_artifact_refs=(),
        evidence_refs=(),
    )
    gateway_context = AgentGatewayContext(
        execution_scope=execution_scope,
        source_platform="investigation_project",
    )
    run = ChildAgentRunRecord(
        definition=ChildAgentRunDefinition(
            agent_run_id="agent-run-1",
            agent_id="researcher",
            task=AgentTask(task_text="Research the bounded topic."),
            context=gateway_context,
        ),
        projection=ChildAgentRunProjection(
            agent_run_id="agent-run-1",
            status="completed",
            result={"answer": content},
        ),
        artifact_index=ChildAgentArtifactIndex(
            agent_run_id="agent-run-1",
            artifacts=(AgentArtifact(
                agent_run_id="agent-run-1",
                kind="markdown_report",
                artifact_ref=artifact_ref,
            ),),
        ),
    )
    proposal = SubGoalExecutionProposal(
        project_id="project-1",
        plan_version=1,
        logical_subgoal_id="research",
        subgoal_version=1,
        based_on_event_sequence=1,
        proposal_id="proposal-agent-1",
        operation=AgentExecutionOperation(
            agent_id="researcher",
            bounded_sub_goal="Research the bounded topic.",
            expected_artifact_types=("markdown_report",),
            token_budget=1_000,
            cost_budget=1,
            time_budget_seconds=60,
        ),
        proposal_digest=canonical_digest({"proposal": "agent-1"}),
    )

    result = DurableProjectAgentAdapter(
        _CompletedGateway(run),
        artifacts,
    ).submit_or_reconcile(
        proposal,
        execution_scope=execution_scope,
        submission_key="submission-agent-1",
    )

    assert result.evidence[0].content_digest == stored_digest
    assert result.evidence[0].artifact_ref == artifact_ref
