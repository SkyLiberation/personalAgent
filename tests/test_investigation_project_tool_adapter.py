from __future__ import annotations

import hashlib

from personal_agent.application.artifacts import ArtifactService
from personal_agent.domain.investigation_project import (
    SubGoalExecutionProposal,
    ToolExecutionOperation,
)
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.scope import (
    ExecutionScope,
    AuthenticatedPrincipal,
)
from personal_agent.orchestration.investigation_project_adapters import (
    ToolExecutorProjectAdapter,
)


class _Executor:
    def invoke_project(self, *args, **kwargs):
        return {
            "ok": True,
            "data": {
                "results": [
                    {
                        "title": "Irrelevant first result",
                        "url": "https://example.test/irrelevant",
                        "snippet": "x" * 700,
                    },
                    {
                        "title": "Formal 2025 release",
                        "url": "https://example.test/formal-2025-release",
                        "snippet": "The formal specification was released on 2025-06-18.",
                    },
                ]
            },
            "evidence": [],
        }


class _ChangingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def invoke_project(self, *args, **kwargs):
        self.calls += 1
        return {
            "ok": True,
            "data": {"result": f"provider observation {self.calls}"},
            "evidence": [],
        }


def test_generated_artifact_preserves_limitations_across_read(temp_dir) -> None:
    principal = AuthenticatedPrincipal(tenant_id="tenant-1", user_id="user-1")
    execution_scope = ExecutionScope(
        principal=principal,
        execution_id="execution-limitations",
        project_id="project-1",
        plan_version=1,
        logical_subgoal_id="report",
        subgoal_version=1,
    )
    artifacts = ArtifactService(Settings(data_dir=temp_dir))

    resource_ref = artifacts.write_generated(
        owner=principal,
        execution_scope=execution_scope,
        producer_key="report:limitations",
        producer_ref="report-1",
        kind="final_report",
        content="Report",
        content_digest=hashlib.sha256(b"Report").hexdigest(),
        source_artifact_refs=(),
        evidence_refs=("ipev-1",),
        limitations=("No migration benchmark was published.",),
    )

    restored = artifacts.read_generated(
        resource_ref,
        principal=principal,
        owner=principal,
    )
    assert restored.limitations == (
        "No migration benchmark was published.",
    )


def test_tool_evidence_materializes_full_output_via_artifact_owner(temp_dir) -> None:
    principal = AuthenticatedPrincipal(tenant_id="tenant-1", user_id="user-1")
    execution_scope = ExecutionScope(
        principal=principal,
        execution_id="execution-1",
        project_id="project-1",
        plan_version=1,
        logical_subgoal_id="search",
        subgoal_version=1,
    )
    operation = ToolExecutionOperation(
        tool_name="web_search",
        typed_arguments={"query": "formal release"},
        expected_artifact_type="search_results",
    )
    proposal = SubGoalExecutionProposal(
        project_id="project-1",
        plan_version=1,
        logical_subgoal_id="search",
        subgoal_version=1,
        based_on_event_sequence=1,
        proposal_id="proposal-1",
        operation=operation,
        proposal_digest="p" * 64,
    )
    artifacts = ArtifactService(Settings(data_dir=temp_dir))
    adapter = ToolExecutorProjectAdapter(_Executor(), artifacts)

    result = adapter.execute(proposal, execution_scope=execution_scope)

    evidence = result.evidence[0]
    assert evidence.artifact_ref is not None
    assert len(evidence.summary) == 500
    materialized = artifacts.read_generated(
        evidence.artifact_ref,
        principal=principal,
        owner=principal,
    )
    assert "https://example.test/formal-2025-release" in materialized.content
    assert "2025-06-18" in materialized.content
    assert evidence.artifact_ref in result.artifact_refs


def test_safe_tool_retry_binds_artifact_to_observed_content(temp_dir) -> None:
    principal = AuthenticatedPrincipal(tenant_id="tenant-1", user_id="user-1")
    execution_scope = ExecutionScope(
        principal=principal,
        execution_id="execution-1",
        project_id="project-1",
        plan_version=1,
        logical_subgoal_id="search",
        subgoal_version=1,
    )
    proposal = SubGoalExecutionProposal(
        project_id="project-1",
        plan_version=1,
        logical_subgoal_id="search",
        subgoal_version=1,
        based_on_event_sequence=1,
        proposal_id="proposal-1",
        operation=ToolExecutionOperation(
            tool_name="web_search",
            typed_arguments={"query": "formal release"},
            expected_artifact_type="search_results",
        ),
        proposal_digest="p" * 64,
    )
    artifacts = ArtifactService(Settings(data_dir=temp_dir))
    adapter = ToolExecutorProjectAdapter(_ChangingExecutor(), artifacts)

    first = adapter.execute(proposal, execution_scope=execution_scope)
    second = adapter.execute(proposal, execution_scope=execution_scope)

    assert first.evidence[0].content_digest != second.evidence[0].content_digest
    assert first.evidence[0].artifact_ref != second.evidence[0].artifact_ref
