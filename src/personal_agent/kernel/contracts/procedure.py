"""Governed procedure contracts.

Procedures protect domain invariants for durable transactions. They are not
task routes and never infer intent from raw user text.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from personal_agent.kernel.contracts.capability import CapabilityRequirement
from personal_agent.kernel.contracts.execution import ExecutionStep

ProcedureStatus = Literal["eligible", "mandatory", "ineligible"]
ProcedureRunStatus = Literal[
    "created", "running", "awaiting_confirmation", "completed", "degraded",
    "cancelled", "failed",
]
ProcedureBranchPolicy = Literal["continue", "clarify", "abort", "human_select", "branch"]

PROCEDURE_END = "END"
PROCEDURE_CLARIFY = "clarify"
PROCEDURE_ABORT = "abort"
PROCEDURE_SENTINELS = frozenset({PROCEDURE_END, PROCEDURE_CLARIFY, PROCEDURE_ABORT})


def _short_id() -> str:
    return uuid4().hex[:12]


@dataclass(frozen=True, slots=True)
class ProcedureCondition:
    condition: str
    target: str


@dataclass(frozen=True, slots=True)
class ProcedureApplicability:
    semantic_domains: tuple[str, ...]
    resource_types: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    required_side_effect_classes: tuple[str, ...] = ()
    mandatory: bool = False


@dataclass(frozen=True, slots=True)
class ProcedureNodeSpec:
    node_id: str
    kind: str
    description: str
    depends_on: tuple[str, ...] = ()
    domain_handler: str | None = None
    capability_requirement: CapabilityRequirement | None = None
    handler_input: dict[str, object] = field(default_factory=dict)
    expected_output: str = ""
    success_criteria: str = ""
    risk_level: str = "low"
    requires_confirmation: bool = False
    on_failure: str = "skip"
    execution_mode: str = "deterministic"
    max_iterations: int = 3
    llm_decision_node: str | None = None
    side_effects: tuple[str, ...] = ()
    hitl_policy: str = "none"
    recovery_policy: str = "skip"
    branch_policy: ProcedureBranchPolicy = "continue"
    conditional_edges: tuple[ProcedureCondition, ...] = ()

    def to_execution_step(self, procedure_id: str, version: str, goal_id: str) -> ExecutionStep:
        requirement = self.capability_requirement
        return ExecutionStep(
            step_id=self.node_id,
            action_type=self.kind,
            description=self.description,
            tool_name=self.domain_handler,
            tool_input=dict(self.handler_input),
            depends_on=list(self.depends_on),
            expected_output=self.expected_output,
            success_criteria=self.success_criteria,
            risk_level=self.risk_level,
            requires_confirmation=self.requires_confirmation,
            on_failure=self.on_failure,
            execution_mode=self.execution_mode,
            max_iterations=self.max_iterations,
            llm_decision_node=self.llm_decision_node or "",
            procedure_id=procedure_id,
            procedure_version=version,
            procedure_node_id=self.node_id,
            procedure_recovery_policy=self.recovery_policy,
            procedure_branch_policy=self.branch_policy,
            conditional_edges=[asdict(edge) for edge in self.conditional_edges],
            projection_kind="procedure_node",
            task_id=goal_id,
            meta_capability="commit" if self.side_effects else self.kind,
            output_contract=requirement.output_contract if requirement else "ToolResult",
            capability_requirements=(
                [requirement.model_dump(mode="json")] if requirement is not None else []
            ),
        )


@dataclass(frozen=True, slots=True)
class ProcedureSpec:
    procedure_id: str
    version: str
    purpose: str
    applicability: ProcedureApplicability
    nodes: tuple[ProcedureNodeSpec, ...]
    input_schema: dict[str, object] = field(default_factory=dict)
    output_schema: dict[str, object] = field(default_factory=dict)
    invariants: tuple[str, ...] = ()
    confirmation_policy: str = "none"
    idempotency_policy: str = "node"
    recovery_policy: str = "branch"
    evidence_required: bool = False

    def project(self, goal_id: str) -> list[ExecutionStep]:
        return [node.to_execution_step(self.procedure_id, self.version, goal_id) for node in self.nodes]

    def to_definition_payload(self) -> dict[str, object]:
        nodes: list[dict[str, object]] = []
        for node in self.nodes:
            payload = asdict(node)
            requirement = node.capability_requirement
            payload["capability_requirement"] = (
                requirement.model_dump(mode="json") if requirement is not None else None
            )
            nodes.append(payload)
        return {
            "procedure_id": self.procedure_id,
            "version": self.version,
            "purpose": self.purpose,
            "applicability": asdict(self.applicability),
            "nodes": nodes,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "invariants": list(self.invariants),
            "confirmation_policy": self.confirmation_policy,
            "idempotency_policy": self.idempotency_policy,
            "recovery_policy": self.recovery_policy,
            "evidence_required": self.evidence_required,
        }

    @classmethod
    def from_definition_payload(cls, payload: dict[str, object]) -> "ProcedureSpec":
        applicability = ProcedureApplicability(**dict(payload.get("applicability") or {}))
        nodes = []
        for raw in payload.get("nodes") or ():
            values = dict(raw)
            requirement = values.get("capability_requirement")
            values["capability_requirement"] = (
                CapabilityRequirement.model_validate(requirement)
                if requirement else None
            )
            values["conditional_edges"] = tuple(
                ProcedureCondition(**dict(edge))
                for edge in values.get("conditional_edges") or ()
            )
            for field_name in (
                "depends_on", "side_effects",
            ):
                values[field_name] = tuple(values.get(field_name) or ())
            nodes.append(ProcedureNodeSpec(**values))
        return cls(
            procedure_id=str(payload.get("procedure_id") or ""),
            version=str(payload.get("version") or ""),
            purpose=str(payload.get("purpose") or ""),
            applicability=applicability,
            nodes=tuple(nodes),
            input_schema=dict(payload.get("input_schema") or {}),
            output_schema=dict(payload.get("output_schema") or {}),
            invariants=tuple(payload.get("invariants") or ()),
            confirmation_policy=str(payload.get("confirmation_policy") or "none"),
            idempotency_policy=str(payload.get("idempotency_policy") or "node"),
            recovery_policy=str(payload.get("recovery_policy") or "branch"),
            evidence_required=bool(payload.get("evidence_required", False)),
        )


class ProcedureCandidate(BaseModel):
    procedure_id: str
    version: str
    goal_id: str
    purpose: str
    status: ProcedureStatus
    matched_requirements: tuple[str, ...] = ()
    rejected_reasons: tuple[str, ...] = ()
    side_effect_class: str = "none"
    requires_confirmation: bool = False


class ProcedureCall(BaseModel):
    procedure_call_id: str = Field(default_factory=_short_id)
    procedure_id: str
    procedure_version: str
    goal_id: str
    input: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    expected_output_contract: str = "ProcedureOutcome"


class ProcedureNodeState(BaseModel):
    node_id: str
    status: str = "planned"
    attempt_count: int = 0
    artifact_ids: tuple[str, ...] = ()


class ProcedureInstance(BaseModel):
    procedure_run_id: str = Field(default_factory=_short_id)
    procedure_id: str
    version: str
    task_id: str
    goal_id: str
    status: ProcedureRunStatus = "created"
    active_node_ids: tuple[str, ...] = ()
    node_states: tuple[ProcedureNodeState, ...] = ()
    input: dict[str, Any] = Field(default_factory=dict)
    artifact_ids: tuple[str, ...] = ()
    receipt_ids: tuple[str, ...] = ()
    revision: int = 1


class ProcedureEvent(BaseModel):
    event_id: str = Field(default_factory=_short_id)
    sequence: int = Field(ge=1)
    procedure_run_id: str
    event_type: Literal[
        "procedure_started", "node_ready", "node_started", "capability_resolved",
        "node_completed", "confirmation_requested", "confirmation_received",
        "mutation_committed", "node_failed", "procedure_degraded",
        "procedure_completed", "procedure_failed",
    ]
    node_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ProcedureOutcome(BaseModel):
    procedure_call_id: str
    procedure_id: str
    status: Literal["completed", "degraded", "cancelled", "failed"]
    artifact_ids: tuple[str, ...] = ()
    mutation_receipt_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    unresolved_conditions: tuple[str, ...] = ()


class ProcedureCatalogPort(Protocol):
    def get(self, procedure_id: str, version: str | None = None) -> ProcedureSpec: ...
    def all_specs(self) -> tuple[ProcedureSpec, ...]: ...


__all__ = [
    "PROCEDURE_ABORT", "PROCEDURE_CLARIFY", "PROCEDURE_END", "PROCEDURE_SENTINELS",
    "ProcedureApplicability", "ProcedureCall", "ProcedureCandidate", "ProcedureCatalogPort",
    "ProcedureCondition", "ProcedureEvent", "ProcedureInstance", "ProcedureNodeSpec",
    "ProcedureNodeState", "ProcedureOutcome", "ProcedureSpec",
]
