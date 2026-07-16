"""Closed execution-grant union consumed by dispatch gateways."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.kernel.contracts.resource import OperationScope, ResourceSelector


class AvailabilityDependency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    capability_ref: str
    availability_revision: int = Field(ge=1)
    valid_until: datetime | None = None


class GrantDependencySet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task_revision: int = Field(ge=1)
    goal_definition_fingerprint: str
    action_fingerprint: str
    plan_id: str | None = None
    plan_revision: int | None = Field(default=None, ge=1)
    step_fingerprint: str | None = None
    capability_definition_revision: int = Field(ge=1)
    provider_binding_revision: int | None = Field(default=None, ge=1)
    availability_dependencies: tuple[AvailabilityDependency, ...] = ()
    authority_revision: int = Field(ge=1)
    policy_bundle_hash: str
    confirmation_revision: int | None = Field(default=None, ge=1)


class AtomicCapabilityGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    grant_kind: Literal["atomic"] = "atomic"
    grant_id: str = Field(default_factory=lambda: uuid4().hex)
    request_id: str
    action_ref: str
    granted_resource_selector: ResourceSelector
    granted_operation_scope: OperationScope
    granted_data_egress: str
    granted_credential_mode: str
    required_confirmation_ref: str | None = None
    retry_family_id: str
    dependency_set: GrantDependencySet
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=10))
    capability_ref: str
    provider_binding_ref: str


class ProcedureGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    grant_kind: Literal["procedure_start"] = "procedure_start"
    grant_id: str = Field(default_factory=lambda: uuid4().hex)
    request_id: str
    action_ref: str
    granted_resource_selector: ResourceSelector
    granted_operation_scope: OperationScope
    granted_data_egress: str
    granted_credential_mode: str
    required_confirmation_ref: str | None = None
    retry_family_id: str
    dependency_set: GrantDependencySet
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=10))
    procedure_id: str
    procedure_version: str
    permission_envelope_ref: str
    receipt_contract: str


class ProcedureNodeGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    grant_kind: Literal["procedure_node"] = "procedure_node"
    grant_id: str = Field(default_factory=lambda: uuid4().hex)
    request_id: str
    action_ref: str
    granted_resource_selector: ResourceSelector
    granted_operation_scope: OperationScope
    granted_data_egress: str
    granted_credential_mode: str
    required_confirmation_ref: str | None = None
    retry_family_id: str
    dependency_set: GrantDependencySet
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=10))
    procedure_run_id: str
    node_id: str
    capability_ref: str
    provider_binding_ref: str


class DelegationGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    grant_kind: Literal["delegation"] = "delegation"
    grant_id: str = Field(default_factory=lambda: uuid4().hex)
    request_id: str
    action_ref: str
    granted_resource_selector: ResourceSelector
    granted_operation_scope: OperationScope
    granted_data_egress: str
    granted_credential_mode: str
    required_confirmation_ref: str | None = None
    retry_family_id: str
    dependency_set: GrantDependencySet
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=10))
    agent_binding_ref: str
    bounded_sub_goal: str
    context_projection_refs: tuple[str, ...] = ()
    token_budget: int = Field(ge=1)
    cost_budget: float = Field(ge=0)
    time_budget_seconds: int = Field(ge=1)
    max_delegation_depth: int = Field(default=0, ge=0)
    completion_contract: str


ExecutionGrant = Annotated[
    AtomicCapabilityGrant | ProcedureGrant | ProcedureNodeGrant | DelegationGrant,
    Field(discriminator="grant_kind"),
]


__all__ = [
    "AtomicCapabilityGrant", "AvailabilityDependency", "DelegationGrant", "ExecutionGrant",
    "GrantDependencySet", "ProcedureGrant", "ProcedureNodeGrant",
]

