"""Capability definitions and independently observed runtime availability."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.capabilities.contracts.execution import Capability, MCPCapability


class ContextCapabilityAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    skill_ref: str
    availability_revision: int = Field(ge=1)
    status: Literal["available", "degraded", "unavailable", "unknown"]
    content_revision: str
    integrity_status: str
    trust_status: str
    compatible_model_purposes: tuple[str, ...] = ()
    observed_at: datetime
    expires_at: datetime | None = None
    reason_codes: tuple[str, ...] = ()


class ExecutionCapabilityAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    capability_ref: str
    availability_revision: int = Field(ge=1)
    status: Literal["available", "degraded", "unavailable", "unknown"]
    credential_ready: bool
    health_observed_at: datetime
    health_expires_at: datetime | None = None
    provider_binding_revision: int = Field(ge=1)
    reason_codes: tuple[str, ...] = ()


class ContextCapabilityAvailabilityProjection(BaseModel):
    observations: dict[str, ContextCapabilityAvailability] = Field(default_factory=dict)


class ExecutionCapabilityAvailabilityProjection(BaseModel):
    observations: dict[str, ExecutionCapabilityAvailability] = Field(default_factory=dict)


class CapabilityPortfolio:
    """Discovery owner; definitions and availability keep separate revisions."""

    def __init__(self, capabilities: Iterable[Capability] = ()) -> None:
        self._definitions: dict[str, Capability] = {}
        self._by_name: dict[str, str] = {}
        self.availability = ExecutionCapabilityAvailabilityProjection()
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: Capability) -> None:
        self._definitions[capability.capability_id] = capability
        if capability.local_name:
            self._by_name[capability.local_name] = capability.capability_id

    def observe(self, observation: ExecutionCapabilityAvailability) -> None:
        if observation.capability_ref not in self._definitions:
            raise KeyError("availability references an unknown capability definition")
        current = self.availability.observations.get(observation.capability_ref)
        if current is not None and observation.availability_revision <= current.availability_revision:
            raise ValueError("availability revision must increase monotonically")
        observations = dict(self.availability.observations)
        observations[observation.capability_ref] = observation
        self.availability = self.availability.model_copy(update={"observations": observations})

    def get(self, capability_id: str) -> Capability | None:
        return self._definitions.get(capability_id)

    def get_by_name(self, local_name: str) -> Capability | None:
        ref = self._by_name.get(local_name)
        return self._definitions.get(ref) if ref else None

    def list(self) -> tuple[Capability, ...]:
        return tuple(
            item for item in self._definitions.values()
            if item.lifecycle != "retired" and self._is_available(item.capability_id)
        )

    def definitions(self) -> tuple[Capability, ...]:
        return tuple(self._definitions.values())

    def by_kind(self, kind: str) -> tuple[Capability, ...]:
        return tuple(item for item in self.list() if item.kind == kind)

    def by_provider(self, provider: str) -> tuple[Capability, ...]:
        return tuple(item for item in self.list() if item.provider == provider)

    def by_domain(self, domain: str) -> tuple[Capability, ...]:
        return tuple(item for item in self.list() if domain in item.semantic_domains)

    def _is_available(self, capability_ref: str) -> bool:
        observation = self.availability.observations.get(capability_ref)
        if observation is None:
            definition = self._definitions[capability_ref]
            return definition.metadata_source == "system" and definition.credential_mode == "none"
        return observation.status in {"available", "degraded"} and observation.credential_ready


class MCPCapabilityPortfolio(CapabilityPortfolio):
    def __init__(self, capabilities: Iterable[MCPCapability] = ()) -> None:
        super().__init__(capabilities)

    def get(self, capability_id: str) -> MCPCapability | None:
        value = super().get(capability_id)
        return value if isinstance(value, MCPCapability) else None

    def get_by_tool(self, tool_name: str) -> MCPCapability | None:
        value = self.get_by_name(tool_name)
        return value if isinstance(value, MCPCapability) else None


__all__ = [
    "CapabilityPortfolio", "ContextCapabilityAvailability",
    "ContextCapabilityAvailabilityProjection", "ExecutionCapabilityAvailability",
    "ExecutionCapabilityAvailabilityProjection", "MCPCapabilityPortfolio",
]
