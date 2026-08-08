from __future__ import annotations

from typing import Protocol

from personal_agent.application.knowledge.models import ConversationSolidifyResult
from personal_agent.application.knowledge_lifecycle.models import KnowledgeDeleteOperationView
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
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import (
    ExecutionScope,
    AuthenticatedPrincipal,
)

from .models import ProjectReference, StartDurableInvestigationArguments, PersonalKnowledgeCandidate


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
        owner: AuthenticatedPrincipal,
    ) -> str: ...

    def write_generated(
        self,
        *,
        owner: AuthenticatedPrincipal,
        execution_scope: ExecutionScope,
        producer_key: str,
        producer_ref: str,
        kind: str,
        content: str,
        content_digest: str,
        source_artifact_refs: tuple[ResourceRef, ...],
        evidence_refs: tuple[str, ...],
        limitations: tuple[str, ...] = (),
    ) -> ResourceRef: ...

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


class ConversationKnowledgeWriter(Protocol):
    def solidify_conversation(
        self,
        messages: list[dict[str, str]],
        *,
        user_id: str,
        owner_id: str,
    ) -> ConversationSolidifyResult: ...


class ConversationKnowledgeReadPort(Protocol):
    def list_personal_knowledge(
        self,
        *,
        owner_id: str,
        user_id: str,
        limit: int,
    ) -> tuple[PersonalKnowledgeCandidate, ...]: ...


class ConversationKnowledgeLifecyclePort(Protocol):
    def prepare_delete(
        self,
        *,
        owner_id: str,
        user_id: str,
        target_note_id: str,
        reason: str,
        idempotency_key: str,
    ) -> KnowledgeDeleteOperationView: ...

    def get_delete(
        self,
        command_id: str,
        *,
        user_id: str,
    ) -> KnowledgeDeleteOperationView | None: ...


class ConversationProjectPort(Protocol):
    def start(
        self,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
        request: StartDurableInvestigationArguments,
        idempotency_key: str,
    ) -> ProjectReference: ...


__all__ = [
    "ConversationKnowledgeLifecyclePort",
    "ConversationKnowledgeWriter",
    "ConversationProjectPort",
    "ConversationKnowledgeReadPort",
    "InteractionAgentPort",
    "InteractionArtifactPort",
    "InteractionToolPort",
]
