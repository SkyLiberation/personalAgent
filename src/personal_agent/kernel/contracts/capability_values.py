"""Stable value taxonomies shared by configuration and capability contracts."""

from typing import Literal

CapabilityKind = Literal["local_tool", "mcp_tool", "retriever", "agent"]
CapabilityOperation = Literal[
    "search", "read", "list", "create", "update", "delete", "delegate",
    "verify", "ingest", "repair",
]
CapabilityTrustLevel = Literal["trusted", "scoped", "external", "untrusted"]
CredentialMode = Literal["user_token", "delegated_token", "service_token", "none"]
DataEgressClass = Literal["none", "metadata", "content", "sensitive"]
AttestationStatus = Literal["verified", "pinned", "self_claimed", "unknown"]
FreshnessProfile = Literal["realtime", "near_realtime", "static", "unknown"]
CapabilityMetadataSource = Literal["system", "provider", "human_reviewed", "llm_inferred"]

__all__ = [
    "AttestationStatus", "CapabilityKind", "CapabilityMetadataSource",
    "CapabilityOperation", "CapabilityTrustLevel", "CredentialMode",
    "DataEgressClass", "FreshnessProfile",
]
