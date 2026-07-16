"""Built-in atomic capability definitions implemented by runtime adapters."""

from personal_agent.capabilities.contracts.execution import EvidenceSourceCapability


def builtin_atomic_capabilities() -> tuple[EvidenceSourceCapability, ...]:
    return (
        EvidenceSourceCapability.from_dimensions(
            capability_id="atomic:local_knowledge_retrieval",
            provider="internal",
            local_name="local_knowledge",
            description="Read and search admitted local knowledge and conversation evidence.",
            semantic_domains=("knowledge", "conversation", "local_memory"),
            resource_types=("note", "evidence", "thread"),
            operations=("search", "read"),
            risk_level="low",
            side_effects=("none",),
            trust_level="trusted",
            credential_mode="none",
            data_egress_class="none",
            attestation_status="verified",
            freshness_profile="static",
            metadata_source="system",
            provider_priority=0,
        ),
    )


__all__ = ["builtin_atomic_capabilities"]

