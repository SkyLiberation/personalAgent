"""External capability contracts.

These contracts describe remote capabilities before they are selected by a
workflow step. They are deliberately separate from ToolGovernance: governance
answers whether a concrete tool invocation is allowed; capability metadata
answers what semantic task a remote MCP tool can satisfy.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

CapabilityOperation = Literal["search", "read", "list", "create", "update", "delete"]
CapabilityTrustLevel = Literal["trusted", "scoped", "external", "untrusted"]
CredentialMode = Literal["user_token", "delegated_token", "service_token", "none"]
DataEgressClass = Literal["none", "metadata", "content", "sensitive"]
AttestationStatus = Literal["verified", "pinned", "self_claimed", "unknown"]
FreshnessProfile = Literal["realtime", "near_realtime", "static", "unknown"]
CapabilityResolutionScope = Literal[
    "external_codebase_qa",
    "external_workspace_qa",
    "external_project_ops",
]


class MCPCapability(BaseModel):
    capability_id: str
    provider: str
    server_id: str
    remote_tool_name: str
    local_tool_name: str
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
    provider_priority: int | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    examples: tuple[dict[str, Any], ...] = ()


class CapabilitySelectionPolicy(BaseModel):
    local_first: bool = True
    read_only: bool = True
    max_capabilities_per_step: int = Field(default=4, ge=1)
    max_providers_per_step: int = Field(default=2, ge=1)
    deny_sensitive_egress: bool = True
    require_trusted_for_sensitive: bool = True
    preferred_providers: tuple[str, ...] = ()


class CapabilityResolutionRequest(BaseModel):
    task_text: str
    workflow_scope: CapabilityResolutionScope
    step_id: str = ""
    allowed_operations: tuple[CapabilityOperation, ...] = ("search", "read", "list")
    policy: CapabilitySelectionPolicy = Field(default_factory=CapabilitySelectionPolicy)


class DeniedCapability(BaseModel):
    capability_id: str
    local_tool_name: str
    provider: str
    reason: str


class CapabilityResolution(BaseModel):
    request: CapabilityResolutionRequest
    selected_capabilities: tuple[MCPCapability, ...] = ()
    denied_capabilities: tuple[DeniedCapability, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    rationale: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


__all__ = [
    "AttestationStatus",
    "CapabilityResolution",
    "CapabilityResolutionRequest",
    "CapabilityResolutionScope",
    "CapabilityOperation",
    "CapabilitySelectionPolicy",
    "CapabilityTrustLevel",
    "CredentialMode",
    "DataEgressClass",
    "DeniedCapability",
    "FreshnessProfile",
    "MCPCapability",
]
