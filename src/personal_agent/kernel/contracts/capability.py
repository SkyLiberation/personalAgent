"""Capability contracts.

Capabilities describe what a bounded action may consider before concrete
execution. They are deliberately separate from Gateway governance:
capability scoping answers "what can this action consider"; gateways answer
"may this concrete invocation run, and how is it audited".
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator
from personal_agent.kernel.contracts.resource import (
    OperationScope,
    ProviderConstraint,
    ResourceSelector,
)

CapabilityKind = Literal[
    "local_tool",
    "mcp_tool",
    "retriever",
    "agent",
]
CapabilityOperation = Literal[
    "search",
    "read",
    "list",
    "create",
    "update",
    "delete",
    "delegate",
    "verify",
    "ingest",
    "repair",
]
CapabilityTrustLevel = Literal["trusted", "scoped", "external", "untrusted"]
CredentialMode = Literal["user_token", "delegated_token", "service_token", "none"]
DataEgressClass = Literal["none", "metadata", "content", "sensitive"]
AttestationStatus = Literal["verified", "pinned", "self_claimed", "unknown"]
FreshnessProfile = Literal["realtime", "near_realtime", "static", "unknown"]
CapabilityMetadataSource = Literal["system", "provider", "human_reviewed", "llm_inferred"]
ResolutionLifecycleState = Literal[
    "created", "resolved", "validated", "policy_clamped", "executed",
    "audited", "rejected", "failed", "superseded",
]
class CapabilityRequirement(BaseModel):
    """A provider-independent requirement for one meta-capability.

    A requirement expresses what a task needs, rather than preselecting a
    provider or a tool name.  Resolver output must report coverage for every
    requirement before a plan can claim that an evidence or action step is
    executable.
    """

    requirement_id: str
    purpose: str
    selector: ResourceSelector = Field(default_factory=ResourceSelector)
    operation_scope: OperationScope = Field(default_factory=OperationScope)
    provider_constraint: ProviderConstraint = Field(default_factory=ProviderConstraint)
    output_contract: str = "ToolResult"

    @classmethod
    def from_dimensions(
        cls,
        *,
        requirement_id: str,
        purpose: str,
        semantic_domains: tuple[str, ...] = (),
        resource_types: tuple[str, ...] = (),
        operations: tuple[CapabilityOperation, ...] = (),
        resource_locator: str | None = None,
        minimum_trust_level: CapabilityTrustLevel = "external",
        freshness_required: bool = False,
        preferred_providers: tuple[str, ...] = (),
        required_providers: tuple[str, ...] = (),
        output_contract: str = "ToolResult",
        side_effect_class: str = "none",
    ) -> "CapabilityRequirement":
        return cls(
            requirement_id=requirement_id,
            purpose=purpose,
            selector=ResourceSelector(
                semantic_domains=frozenset(semantic_domains),
                resource_types=frozenset(resource_types),
                locator=resource_locator,
            ),
            operation_scope=OperationScope(
                operations=frozenset(operations), side_effect_class=side_effect_class,
            ),
            provider_constraint=ProviderConstraint(
                required=frozenset(required_providers),
                preferred=preferred_providers,
                freshness_required=freshness_required,
                minimum_trust=minimum_trust_level,
            ),
            output_contract=output_contract,
        )

    @property
    def semantic_domains(self) -> tuple[str, ...]:
        return tuple(sorted(self.selector.semantic_domains))

    @property
    def resource_types(self) -> tuple[str, ...]:
        return tuple(sorted(self.selector.resource_types))

    @property
    def operations(self) -> tuple[CapabilityOperation, ...]:
        return tuple(sorted(self.operation_scope.operations))  # type: ignore[return-value]

    @property
    def resource_locator(self) -> str | None:
        return self.selector.locator

    @property
    def minimum_trust_level(self) -> CapabilityTrustLevel:
        return self.provider_constraint.minimum_trust  # type: ignore[return-value]

    @property
    def freshness_required(self) -> bool:
        return self.provider_constraint.freshness_required

    @property
    def preferred_providers(self) -> tuple[str, ...]:
        return self.provider_constraint.preferred

    @property
    def required_providers(self) -> tuple[str, ...]:
        return tuple(sorted(self.provider_constraint.required))

    @property
    def side_effect_class(self) -> str:
        return self.operation_scope.side_effect_class


class CapabilityCoverage(BaseModel):
    """Auditable proof of whether a requirement can be fulfilled."""

    requirement_id: str
    status: Literal["satisfied", "partial", "unavailable", "denied"]
    selected_capability_ids: tuple[str, ...] = ()
    missing_operations: tuple[CapabilityOperation, ...] = ()
    resource_bound: bool = False
    authority_satisfied: bool = False
    freshness_satisfied: bool = False
    rationale: str = ""


class Capability(BaseModel):
    capability_id: str
    kind: CapabilityKind
    provider: str
    local_name: str | None = None
    description: str = ""
    selector: ResourceSelector = Field(default_factory=ResourceSelector)
    operation_scope: OperationScope = Field(default_factory=OperationScope)
    risk_level: str = "low"
    side_effects: tuple[str, ...] = ("none",)
    auth_scope: str = "mcp:tool"
    trust_level: CapabilityTrustLevel = "external"
    credential_mode: CredentialMode = "delegated_token"
    data_egress_class: DataEgressClass = "content"
    attestation_status: AttestationStatus = "self_claimed"
    freshness_profile: FreshnessProfile = "unknown"
    metadata_source: CapabilityMetadataSource = "provider"
    metadata_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    selectable: bool = True
    selectable_only_in_actions: tuple[str, ...] = ()
    provider_priority: int | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    examples: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_dimensions(cls, **values: Any) -> "Capability":
        semantic_domains = tuple(values.pop("semantic_domains", ()))
        resource_types = tuple(values.pop("resource_types", ()))
        operations = tuple(values.pop("operations", ()))
        side_effects = tuple(values.get("side_effects", ("none",)))
        values["selector"] = ResourceSelector(
            semantic_domains=frozenset(semantic_domains),
            resource_types=frozenset(resource_types),
        )
        values["operation_scope"] = OperationScope(
            operations=frozenset(operations),
            side_effect_class=next((item for item in side_effects if item != "none"), "none"),
        )
        return cls(**values)

    @property
    def semantic_domains(self) -> tuple[str, ...]:
        return tuple(sorted(self.selector.semantic_domains))

    @property
    def resource_types(self) -> tuple[str, ...]:
        return tuple(sorted(self.selector.resource_types))

    @property
    def operations(self) -> tuple[CapabilityOperation, ...]:
        return tuple(sorted(self.operation_scope.operations))  # type: ignore[return-value]


class MCPCapability(Capability):
    kind: CapabilityKind = "mcp_tool"
    server_id: str
    remote_tool_name: str
    credential_mode: CredentialMode = "delegated_token"
    data_egress_class: DataEgressClass = "content"


class EvidenceSourceCapability(Capability):
    """A governed capability exposed to ask as one evidence source.

    The source may execute through a retriever, ToolGateway, or AgentGateway,
    but ask only receives the retrieval-source contract.
    """

    kind: CapabilityKind = "retriever"
    exposed_as: Literal["retrieval_source"] = "retrieval_source"
    underlying_execution: Literal["retriever", "tool_gateway", "agent_gateway"] = "retriever"


class EscalationHint(BaseModel):
    reason: Literal["insufficient_evidence", "freshness_needed", "capability_missing"]
    requested_domains: tuple[str, ...] = ()
    requested_operations: tuple[CapabilityOperation, ...] = ()
    suggested_execution_shape: str | None = None

class CapabilitySelectionPolicy(BaseModel):
    local_first: bool = False
    read_only: bool = True
    max_capabilities_per_action: int = Field(default=4, ge=1)
    max_providers_per_action: int = Field(default=2, ge=1)
    deny_sensitive_egress: bool = True
    require_trusted_for_sensitive: bool = True
    require_reviewed_metadata_for_high_risk: bool = True
    preferred_providers: tuple[str, ...] = ()


class CapabilityResolutionRequest(BaseModel):
    scope_id: str | None = None
    task_id: str = Field(min_length=1)
    goal_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    meta_capability: str
    allowed_kinds: tuple[CapabilityKind, ...] = ("mcp_tool",)
    allowed_operations: tuple[CapabilityOperation, ...] = ("search", "read", "list")
    requirements: tuple[CapabilityRequirement, ...] = ()
    policy: CapabilitySelectionPolicy = Field(default_factory=CapabilitySelectionPolicy)
    runtime_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _assign_scope_id(self) -> "CapabilityResolutionRequest":
        if self.scope_id is not None:
            return self
        identity = ":".join((
            self.task_id,
            self.goal_id,
            self.action_id,
            self.meta_capability,
        ))
        self.scope_id = sha256(identity.encode("utf-8")).hexdigest()[:16]
        return self


class DeniedCapability(BaseModel):
    capability_id: str
    local_name: str = ""
    provider: str
    reason: str


class ResolutionEvent(BaseModel):
    sequence: int = Field(ge=1)
    resolution_id: str = Field(min_length=1)
    state: ResolutionLifecycleState
    reason: str = ""
    trace_ref: str = ""


class ResolutionRunProjection(BaseModel):
    resolution_id: str = Field(min_length=1)
    lifecycle: ResolutionLifecycleState = "created"
    last_event_sequence: int = 0
    failure_reason: str | None = None


class ResolutionConstraints(BaseModel):
    task_id: str
    goal_id: str
    action_id: str
    meta_capability: str
    allowed_kinds: tuple[CapabilityKind, ...] = ()
    allowed_operations: tuple[CapabilityOperation, ...] = ()
    hard_denied_capability_ids: tuple[str, ...] = ()
    ranking: dict[str, Any] = Field(default_factory=dict)
    validator_errors: tuple[str, ...] = ()


class CapabilityEvidencePack(BaseModel):
    scope_id: str
    resolution_id: str
    selected_capability_ids: tuple[str, ...] = ()
    denied_capability_ids: tuple[str, ...] = ()
    tool_calls: tuple[dict[str, Any], ...] = ()
    sources: tuple[dict[str, Any], ...] = ()
    snippets: tuple[dict[str, Any], ...] = ()
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_sufficiency: Literal["sufficient", "partial", "insufficient"] = "insufficient"
    citation_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    freshness_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    unresolved_questions: tuple[str, ...] = ()


class CapabilityResolutionDecision(BaseModel):
    resolution_id: str = Field(default_factory=lambda: uuid4().hex)
    request_scope_id: str = Field(min_length=1)
    validation_state: Literal["validated", "rejected"] = "validated"
    selected_capabilities: tuple[Capability, ...] = ()
    denied_capabilities: tuple[DeniedCapability, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    selected_retrievers: tuple[str, ...] = ()
    allowed_agents: tuple[str, ...] = ()
    coverage: tuple[CapabilityCoverage, ...] = ()
    constraints: ResolutionConstraints
    escalation_hint: EscalationHint | None = None
    rationale: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)



def project_resolution_event(
    projection: ResolutionRunProjection,
    event: ResolutionEvent,
) -> ResolutionRunProjection:
    if event.resolution_id != projection.resolution_id:
        raise ValueError("resolution event identity mismatch")
    if event.sequence != projection.last_event_sequence + 1:
        raise ValueError("resolution event sequence mismatch")
    return projection.model_copy(update={
        "lifecycle": event.state,
        "last_event_sequence": event.sequence,
        "failure_reason": event.reason if event.state in {"failed", "rejected"} else None,
    })


__all__ = [
    "AttestationStatus",
    "Capability",
    "CapabilityCoverage",
    "CapabilityKind",
    "CapabilityMetadataSource",
    "CapabilityResolutionDecision",
    "CapabilityResolutionRequest",
    "CapabilityRequirement",
    "CapabilityOperation",
    "CapabilitySelectionPolicy",
    "CapabilityTrustLevel",
    "CredentialMode",
    "DataEgressClass",
    "DeniedCapability",
    "EscalationHint",
    "CapabilityEvidencePack",
    "EvidenceSourceCapability",
    "FreshnessProfile",
    "MCPCapability",
    "ResolutionLifecycleState",
    "ResolutionConstraints",
    "ResolutionEvent",
    "ResolutionRunProjection",
    "project_resolution_event",
]
