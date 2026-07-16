"""Capability acquisition management contracts; acquisition is never Goal progress."""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.capabilities.contracts.execution import CapabilityRequirement


class CapabilityAcquisitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    task_id: str
    goal_id: str
    requirement: CapabilityRequirement
    method: Literal["suggest", "install", "enable", "connect", "request_auth"] = "suggest"
    requires_user_approval: bool = True
    source_allowlist_ref: str = "capability-sources:v1"
    policy_revision: str = "v1"


class CapabilityAcquisitionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str
    status: Literal["suggested", "approved", "denied", "completed", "failed"]
    environment_changed: bool = False
    new_discovery_required: bool = False
    reason_codes: tuple[str, ...] = ()


class CapabilityAcquisitionProjection(BaseModel):
    requests: dict[str, CapabilityAcquisitionRequest] = Field(default_factory=dict)
    outcomes: dict[str, CapabilityAcquisitionOutcome] = Field(default_factory=dict)


__all__ = [
    "CapabilityAcquisitionOutcome", "CapabilityAcquisitionProjection",
    "CapabilityAcquisitionRequest",
]

