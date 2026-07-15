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
    semantic_domains: tuple[str, ...] = ()
    resource_types: tuple[str, ...] = ()
    operations: tuple[CapabilityOperation, ...] = ()
    resource_locator: str | None = None
    minimum_trust_level: CapabilityTrustLevel = "external"
    freshness_required: bool = False
    preferred_providers: tuple[str, ...] = ()
    required_providers: tuple[str, ...] = ()
    output_contract: str = "ToolResult"
    side_effect_class: str = "none"


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
    semantic_domains: tuple[str, ...] = ()
    resource_types: tuple[str, ...] = ()
    operations: tuple[CapabilityOperation, ...] = ()
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
    scope_id: str = ""
    task_id: str = ""
    goal_id: str
    action_id: str
    meta_capability: str
    allowed_kinds: tuple[CapabilityKind, ...] = ("mcp_tool",)
    allowed_operations: tuple[CapabilityOperation, ...] = ("search", "read", "list")
    requirements: tuple[CapabilityRequirement, ...] = ()
    policy: CapabilitySelectionPolicy = Field(default_factory=CapabilitySelectionPolicy)
    runtime_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _assign_scope_id(self) -> "CapabilityResolutionRequest":
        if self.scope_id:
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


class ResolutionLifecycleEvent(BaseModel):
    state: ResolutionLifecycleState
    reason: str = ""
    trace_ref: str = ""


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


class CapabilityResolution(BaseModel):
    request: CapabilityResolutionRequest
    resolution_id: str = Field(default_factory=lambda: uuid4().hex)
    lifecycle_state: ResolutionLifecycleState = "created"
    lifecycle_events: tuple[ResolutionLifecycleEvent, ...] = ()
    selected_capabilities: tuple[Capability, ...] = ()
    denied_capabilities: tuple[DeniedCapability, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    selected_retrievers: tuple[str, ...] = ()
    allowed_agents: tuple[str, ...] = ()
    coverage: tuple[CapabilityCoverage, ...] = ()
    constraints: dict[str, Any] = Field(default_factory=dict)
    escalation_hint: EscalationHint | None = None
    rationale: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    def transition(
        self,
        state: ResolutionLifecycleState,
        *,
        reason: str = "",
        trace_ref: str = "",
    ) -> "CapabilityResolution":
        return self.model_copy(update={
            "lifecycle_state": state,
            "lifecycle_events": (*self.lifecycle_events, ResolutionLifecycleEvent(
                state=state,
                reason=reason,
                trace_ref=trace_ref,
            )),
        })


__all__ = [
    "AttestationStatus",
    "Capability",
    "CapabilityCoverage",
    "CapabilityKind",
    "CapabilityMetadataSource",
    "CapabilityResolution",
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
    "ResolutionLifecycleEvent",
    "ResolutionLifecycleState",
]
