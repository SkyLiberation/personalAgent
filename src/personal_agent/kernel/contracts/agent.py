from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Protocol
from uuid import uuid4

AgentProtocol = Literal["a2a_jsonrpc", "local", "http"]
AgentRunStatus = Literal["submitted", "working", "completed", "failed", "canceled"]
AgentEventType = Literal[
    "submitted",
    "status_changed",
    "stream_delta",
    "artifact_created",
    "completed",
    "failed",
    "canceled",
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
class AgentDefinition:
    agent_id: str
    provider: str
    protocol: AgentProtocol
    description: str = ""
    semantic_domains: tuple[str, ...] = ()
    task_types: tuple[str, ...] = ()
    governance: AgentGovernance = field(default_factory=AgentGovernance)


@dataclass(frozen=True, slots=True)
class AgentTask:
    task_text: str
    task_type: str = "research"
    input: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentGatewayContext:
    user_id: str
    session_id: str
    run_id: str
    thread_id: str = ""
    workflow_id: str = ""
    step_id: str = ""
    source_platform: str = ""
    confirmed: bool = False


@dataclass(frozen=True, slots=True)
class AgentArtifact:
    artifact_id: str
    agent_run_id: str
    kind: str
    content: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    verification_status: Literal["unverified", "verified", "rejected"] = "unverified"


@dataclass(frozen=True, slots=True)
class AgentEvent:
    event_id: str
    agent_run_id: str
    type: AgentEventType
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentRun:
    agent_run_id: str
    agent_id: str
    status: AgentRunStatus
    task: AgentTask
    context: AgentGatewayContext
    external_task_id: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    artifacts: tuple[AgentArtifact, ...] = ()
    events: tuple[AgentEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    run: AgentRun
    output_text: str = ""
    artifacts: tuple[AgentArtifact, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentAdapter(Protocol):
    definition: AgentDefinition

    def invoke(self, task: AgentTask, context: AgentGatewayContext) -> AgentRunResult: ...

    def submit(self, task: AgentTask, context: AgentGatewayContext) -> AgentRun: ...

    def poll(self, agent_run_id: str, context: AgentGatewayContext) -> AgentRun: ...

    def cancel(self, agent_run_id: str, context: AgentGatewayContext) -> AgentRun: ...

    def stream(self, agent_run_id: str, context: AgentGatewayContext) -> Iterator[AgentEvent]: ...


def new_agent_run_id() -> str:
    return f"arun_{uuid4().hex[:16]}"


def new_agent_event_id() -> str:
    return f"aevt_{uuid4().hex[:16]}"


def new_agent_artifact_id() -> str:
    return f"aart_{uuid4().hex[:16]}"


__all__ = [
    "AgentAdapter",
    "AgentArtifact",
    "AgentDefinition",
    "AgentEvent",
    "AgentEventType",
    "AgentGatewayContext",
    "AgentGovernance",
    "AgentProtocol",
    "AgentRun",
    "AgentRunResult",
    "AgentRunStatus",
    "AgentTask",
    "new_agent_artifact_id",
    "new_agent_event_id",
    "new_agent_run_id",
]
