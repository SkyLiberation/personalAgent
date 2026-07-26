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
        action_id: str,
        run_id: str,
        user_id: str,
        conversation_id: str,
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
    ) -> ChildAgentRunRecord: ...

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


__all__ = ["InteractionAgentPort", "InteractionToolPort"]
