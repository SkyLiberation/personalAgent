from __future__ import annotations

from typing import Protocol

from personal_agent.capabilities.contracts.grants import DelegationGrant
from personal_agent.capabilities.contracts.interaction import (
    InteractionToolCallValidation,
    InteractionToolDefinition,
)
from personal_agent.kernel.contracts.agent import (
    AgentGatewayContext,
    AgentTask,
    ChildAgentRunRecord,
    SubagentProfile,
)
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import (
    AuthenticatedPrincipal,
    SecurityScope,
)


class InteractionToolPort(Protocol):
    def list_interaction_tools(self) -> tuple[InteractionToolDefinition, ...]: ...

    def validate_interaction_call(
        self,
        name: str,
        arguments: dict[str, object],
    ) -> InteractionToolCallValidation: ...

    def interaction_call_is_safe_for_concurrency(self, name: str) -> bool: ...

    def invoke_interaction(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        execution_scope: ExecutionScope,
        tool_call_id: str,
        source_platform: str,
    ) -> dict[str, object]: ...


class InteractionAgentPort(Protocol):
    def profiles(self) -> tuple[SubagentProfile, ...]: ...

    def profile(self, agent_id: str) -> SubagentProfile | None: ...

    def submit(
        self,
        agent_id: str,
        task: AgentTask,
        context: AgentGatewayContext,
        grant: DelegationGrant,
        *,
        submission_key: str,
    ) -> ChildAgentRunRecord: ...


class InteractionArtifactPort(Protocol):
    def read_text(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        security_scope: SecurityScope,
    ) -> str: ...

    def poll(
        self,
        agent_run_id: str,
        context: AgentGatewayContext,
    ) -> ChildAgentRunRecord: ...

    def cancel(
        self,
        agent_run_id: str,
        context: AgentGatewayContext,
    ) -> ChildAgentRunRecord: ...


__all__ = [
    "InteractionAgentPort",
    "InteractionArtifactPort",
    "InteractionToolPort",
]
