from __future__ import annotations

import json
from pathlib import Path

from evals.agent_gateway_quality.dataset import load_cases
from evals.agent_gateway_quality.scorer import AgentGatewayQualityRun, score_all
from personal_agent.agents import AgentGateway, InMemoryAgentRunStore
from personal_agent.capabilities.contracts.grants import (
    DelegationGrant,
    GrantDependencySet,
)
from personal_agent.governance.policy import PolicyEngine
from personal_agent.kernel.contracts.agent import (
    AgentArtifact,
    AgentGatewayContext,
    AgentGovernance,
    AgentTask,
    ChildAgentArtifactIndex,
    ChildAgentRunDefinition,
    ChildAgentRunEvent,
    ChildAgentRunOutcome,
    ChildAgentRunProjection,
    ChildAgentRunRecord,
    SubagentProfile,
    new_agent_event_id,
    new_agent_run_id,
)
from personal_agent.kernel.contracts.resource import (
    OperationScope,
    ResourceRef,
    ResourceSelector,
)
from personal_agent.kernel.contracts.scope import (
    interaction_execution_scope,
)


def test_agent_gateway_quality_gate():
    cases = load_cases()
    runs = tuple(_run_case(case) for case in cases)
    report = score_all(cases, runs)
    baseline = json.loads(
        Path(__file__).with_name("baseline.json").read_text(encoding="utf-8")
    )
    failures = report.check_thresholds(baseline)
    assert not failures, "\n".join(failures)


def _run_case(case) -> AgentGatewayQualityRun:
    gateway = AgentGateway(
        policy_engine=PolicyEngine(),
        store=InMemoryAgentRunStore(),
    )
    gateway.register(_QualityAgent(
        "gpt_researcher",
        permission_scope="a2a:gpt_researcher:research",
    ))
    gateway.register(_QualityAgent(
        "secondary_researcher",
        permission_scope="a2a:secondary:research",
    ))
    action_id = f"{case.id}:delegate"
    context = AgentGatewayContext(
        execution_scope=interaction_execution_scope(
            tenant_id="quality",
            user_id="quality",
            execution_id=f"entry-{case.id}",
            task_id=action_id,
        ),
        source_platform="agent_gateway_quality",
    )
    task = AgentTask(task_text="Agent2Agent adoption", task_type="research")
    grant = _grant(case.agent_id, action_id)

    if case.operation in {"invoke", "multi_agent_selection"}:
        run = gateway.invoke(
            case.agent_id,
            task,
            context,
            grant,
            submission_key=f"quality:{case.id}",
        ).run
        stream_events: tuple[str, ...] = ()
    else:
        submitted = gateway.submit(
            case.agent_id,
            task,
            context,
            grant,
            submission_key=f"quality:{case.id}",
        )
        run_id = submitted.definition.agent_run_id
        if case.operation == "submit_poll":
            run = gateway.poll(run_id, context)
            stream_events = ()
        elif case.operation == "cancel":
            run = gateway.cancel(run_id, context)
            stream_events = ()
        elif case.operation == "stream":
            stream = tuple(gateway.stream(run_id, context))
            run = gateway.get_run(run_id) or submitted
            stream_events = tuple(event.type for event in stream)
        else:
            raise AssertionError(f"unknown operation={case.operation!r}")

    profile = gateway.profile(run.definition.agent_id)
    return AgentGatewayQualityRun(
        case_id=case.id,
        agent_id=run.definition.agent_id,
        status=run.projection.status,
        permission_scope=profile.governance.permission_scope if profile else "",
        artifact_statuses=tuple(
            artifact.producer_verification_status
            for artifact in run.artifact_index.artifacts
        ),
        event_types=tuple(event.type for event in run.events),
        stream_event_types=stream_events,
    )


class _QualityAgent:
    def __init__(self, agent_id: str, *, permission_scope: str) -> None:
        self.profile = SubagentProfile(
            agent_id=agent_id,
            provider=agent_id,
            protocol="local",
            semantic_domains=("external_research",),
            task_types=("research",),
            governance=AgentGovernance(
                permission_scope=permission_scope,
                risk_level="medium",
                side_effects=("external_network",),
            ),
        )

    def invoke(
        self,
        task: AgentTask,
        context: AgentGatewayContext,
    ) -> ChildAgentRunOutcome:
        return ChildAgentRunOutcome(
            run=self._run(task, context, status="completed"),
            output_text="quality report",
        )

    def submit(
        self,
        task: AgentTask,
        context: AgentGatewayContext,
        *,
        submission_key: str,
    ) -> ChildAgentRunRecord:
        return self._run(task, context, status="running")

    def lookup_submission(self, submission_key, task, context):
        return None

    def poll(self, run, context):
        return self._run(
            run.definition.task,
            context,
            status="completed",
            agent_run_id=run.definition.agent_run_id,
        )

    def cancel(self, run, context):
        return self._run(
            run.definition.task,
            context,
            status="cancelled",
            agent_run_id=run.definition.agent_run_id,
        )

    def stream(self, run, context):
        yield ChildAgentRunEvent(
            event_id=new_agent_event_id(),
            agent_run_id=run.definition.agent_run_id,
            type="stream_delta",
            payload={"delta": "quality"},
        )

    def _run(self, task, context, *, status, agent_run_id=None):
        run_id = agent_run_id or new_agent_run_id()
        artifact = AgentArtifact(
            agent_run_id=run_id,
            kind="markdown_report",
            artifact_ref=ResourceRef(
                resource_id=f"quality-artifact-{run_id}",
                resource_type="artifact",
                owner=context.execution_scope.principal,
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
                status=status,
                external_task_id="quality-task",
                result={"report_ref": artifact.artifact_ref.resource_id},
            ),
            artifact_index=ChildAgentArtifactIndex(
                agent_run_id=run_id,
                artifacts=(artifact,),
            ),
            events=(ChildAgentRunEvent(
                event_id=new_agent_event_id(),
                agent_run_id=run_id,
                type="status_changed",
                payload={"status": status},
            ),),
        )


def _grant(agent_id: str, action_id: str) -> DelegationGrant:
    return DelegationGrant(
        request_id=f"quality:{action_id}",
        action_ref=action_id,
        authorization_digest="quality-authorization",
        execution_command_digest="quality-command",
        granted_resource_selector=ResourceSelector(),
        granted_operation_scope=OperationScope(
            operations=frozenset({"delegate"})
        ),
        granted_data_egress="content",
        granted_credential_mode="none",
        retry_family_id=action_id,
        dependency_set=GrantDependencySet(
            task_revision=1,
            goal_definition_fingerprint=action_id,
            action_fingerprint=action_id,
            capability_definition_revision=1,
            authority_revision=1,
            policy_bundle_hash="quality",
        ),
        agent_binding_ref=f"quality:{agent_id}",
        bounded_sub_goal="quality research",
        token_budget=1000,
        cost_budget=1,
        time_budget_seconds=60,
        completion_contract="AgentArtifact",
    )
