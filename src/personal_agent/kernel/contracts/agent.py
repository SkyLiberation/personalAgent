from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Protocol
from uuid import uuid4

from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.contracts.resource import ResourceRef
AgentProtocol = Literal["a2a_jsonrpc", "local", "http"]
ChildAgentRunStatus = Literal[
    "created", "queued", "running", "waiting", "blocked_approval",
    "cancel_requested", "cancelling", "completed", "completed_degraded",
    "cancelled", "failed", "timed_out",
]
ChildAgentRunEventType = Literal[
    "submitted",
    "status_changed",
    "stream_delta",
    "artifact_created",
    "completed",
    "failed",
    "cancelled",
]


@dataclass(frozen=True, slots=True)
class AgentGovernance:
    exposure: str = "public_agent"
    risk_level: str = "medium"
    side_effects: tuple[str, ...] = ("external_network",)
    permission_scope: str = "agent:invoke"
    data_egress_class: str = "content"
    trust_level: str = "external"
    timeout_seconds: float = 120.0
    rate_limit_per_minute: int | None = None
    allowed_domains: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SubagentProfile:
    agent_id: str
    provider: str
    protocol: AgentProtocol
    description: str = ""
    semantic_domains: tuple[str, ...] = ()
    task_types: tuple[str, ...] = ()
    model_profile: str = "default"
    skill_ids: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()
    allowed_operations: tuple[str, ...] = ()
    max_turns: int = 12
    max_runtime_seconds: int = 120
    can_delegate: bool = False
    governance: AgentGovernance = field(default_factory=AgentGovernance)


@dataclass(frozen=True, slots=True)
class AgentTask:
    task_text: str
    task_type: str = "research"
    input: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentGatewayContext:
    execution_scope: ExecutionScope
    source_platform: str = ""
    confirmed: bool = False


@dataclass(frozen=True, slots=True)
class AgentArtifact:
    agent_run_id: str
    kind: str
    artifact_ref: ResourceRef
    producer_verification_status: Literal["unverified", "verified", "rejected"] = "unverified"


@dataclass(frozen=True, slots=True)
class ChildAgentRunEvent:
    event_id: str
    agent_run_id: str
    type: ChildAgentRunEventType
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChildAgentRunDefinition:
    agent_run_id: str
    agent_id: str
    task: AgentTask
    context: AgentGatewayContext
    submission_key: str = ""
    authorization_digest: str = ""
    execution_command_digest: str = ""


@dataclass(frozen=True, slots=True)
class ChildAgentRunProjection:
    agent_run_id: str
    status: ChildAgentRunStatus
    external_task_id: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ChildAgentArtifactIndex:
    agent_run_id: str
    artifacts: tuple[AgentArtifact, ...] = ()


@dataclass(frozen=True, slots=True)
class ChildAgentRunRecord:
    definition: ChildAgentRunDefinition
    projection: ChildAgentRunProjection
    artifact_index: ChildAgentArtifactIndex
    events: tuple[ChildAgentRunEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class ReservedAgentSubmission:
    run: ChildAgentRunRecord
    created: bool


@dataclass(frozen=True, slots=True)
class ChildAgentRunOutcome:
    run: ChildAgentRunRecord
    output_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentAdapter(Protocol):
    profile: SubagentProfile

    def invoke(self, task: AgentTask, context: AgentGatewayContext) -> ChildAgentRunOutcome: ...

    def submit(
        self,
        task: AgentTask,
        context: AgentGatewayContext,
        *,
        submission_key: str,
    ) -> ChildAgentRunRecord: ...

    def lookup_submission(
        self,
        submission_key: str,
        task: AgentTask,
        context: AgentGatewayContext,
    ) -> ChildAgentRunRecord | None: ...

    def poll(self, run: ChildAgentRunRecord, context: AgentGatewayContext) -> ChildAgentRunRecord: ...

    def cancel(self, run: ChildAgentRunRecord, context: AgentGatewayContext) -> ChildAgentRunRecord: ...

    def stream(self, run: ChildAgentRunRecord, context: AgentGatewayContext) -> Iterator[ChildAgentRunEvent]: ...


def new_agent_run_id() -> str:
    return f"arun_{uuid4().hex[:16]}"


def new_agent_event_id() -> str:
    return f"aevt_{uuid4().hex[:16]}"


def new_agent_artifact_id() -> str:
    return f"aart_{uuid4().hex[:16]}"


__all__ = [
    "AgentAdapter",
    "AgentArtifact",
    "ChildAgentArtifactIndex",
    "ChildAgentRunDefinition",
    "ChildAgentRunEvent",
    "ChildAgentRunEventType",
    "AgentGatewayContext",
    "AgentGovernance",
    "AgentProtocol",
    "ChildAgentRunProjection",
    "ChildAgentRunRecord",
    "ReservedAgentSubmission",
    "ChildAgentRunOutcome",
    "ChildAgentRunStatus",
    "AgentTask",
    "SubagentProfile",
    "new_agent_artifact_id",
    "new_agent_event_id",
    "new_agent_run_id",
]
