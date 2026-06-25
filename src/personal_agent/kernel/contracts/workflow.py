"""Workflow definition contracts (durable data + serialization).

``WorkflowSpec`` / ``WorkflowStepSpec`` describe the *durable* shape of a business
workflow. They live in the kernel so the infra layer (the workflow definition /
deployment store) can persist and restore them without importing the planning
package. The concrete ``WorkflowRegistry`` and the in-repo flow definitions stay
in the planning layer; lower layers that only need to select/list specs depend on
the :class:`WorkflowRegistryProtocol` structural type instead.

The runtime projection (``ExecutionStep``) is also a kernel contract, so the
``to_projection`` / ``project`` helpers can stay on these dataclasses without
pulling in any higher layer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Protocol

from personal_agent.kernel.models import EntryIntent
from personal_agent.kernel.contracts.execution import ExecutionStep

ProjectionPolicy = Literal["none", "step_projection"]

# Branch semantics taken when a step finishes or cannot resolve. ``continue``
# advances to dependents by the normal dependency loop; the others describe how
# the workflow diverges from the happy path. ``human_select`` marks a node that
# must surface candidates for explicit user choice (e.g. multi-candidate delete).
BranchPolicy = Literal["continue", "clarify", "abort", "human_select", "branch"]

# Terminal sentinels a conditional edge may target instead of another step id.
EDGE_END = "END"
EDGE_CLARIFY = "clarify"
EDGE_ABORT = "abort"
EDGE_SENTINELS = frozenset({EDGE_END, EDGE_CLARIFY, EDGE_ABORT})


@dataclass(frozen=True, slots=True)
class WorkflowConditionalEdge:
    """A declarative conditional transition out of a workflow node.

    ``condition`` is a stable, human-readable label for the branch trigger
    (e.g. ``"no_candidate"``, ``"rejected"``). ``target`` is either another
    step id within the same workflow or one of :data:`EDGE_SENTINELS`. The edge
    is a contract describing *intended* control flow so that
    ``WorkflowSpecValidator`` can keep it consistent with the executable graph;
    it does not by itself rewire LangGraph.
    """

    condition: str
    target: str


@dataclass(frozen=True, slots=True)
class WorkflowStepSpec:
    """A node-level contract inside a workflow.

    The fields intentionally mirror the runtime projection shape where useful,
    but this object is stronger than ``ExecutionStep``: it belongs to the workflow
    source of truth and can carry non-UI contracts such as decision node names,
    side effects, HITL policy, node recovery policy, and the conditional edges
    that describe how the workflow diverges from the happy path.
    """

    step_id: str
    action_type: str
    description: str
    tool_name: str | None = None
    tool_input: dict[str, object] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    expected_output: str = ""
    success_criteria: str = ""
    risk_level: str = "low"
    requires_confirmation: bool = False
    on_failure: str = "skip"
    execution_mode: str = "deterministic"
    allowed_tools: tuple[str, ...] = ()
    max_iterations: int = 3
    llm_decision_node: str | None = None
    side_effects: tuple[str, ...] = ()
    hitl_policy: str = "none"
    recovery_policy: str = "skip"
    branch_policy: BranchPolicy = "continue"
    conditional_edges: tuple[WorkflowConditionalEdge, ...] = ()
    project_to_plan: bool = True

    def to_projection(self, workflow_id: str, workflow_version: str) -> ExecutionStep:
        """Create a fresh runtime step projection for this workflow node."""
        return ExecutionStep(
            step_id=self.step_id,
            action_type=self.action_type,
            description=self.description,
            tool_name=self.tool_name,
            tool_input=dict(self.tool_input),
            depends_on=list(self.depends_on),
            expected_output=self.expected_output,
            success_criteria=self.success_criteria,
            risk_level=self.risk_level,
            requires_confirmation=self.requires_confirmation,
            on_failure=self.on_failure,
            status="planned",
            retry_count=0,
            execution_mode=self.execution_mode,
            allowed_tools=list(self.allowed_tools),
            max_iterations=self.max_iterations,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            workflow_step_id=self.step_id,
            projection_kind="workflow_step",
        )


@dataclass(frozen=True, slots=True)
class WorkflowSpec:
    """A declarative workflow contract.

    ``projection_policy='step_projection'`` means selected ``WorkflowStepSpec``
    nodes are surfaced as runtime ``ExecutionStep`` projections. ``projection_policy``
    is intentionally explicit so ordinary workflows can still have rich node
    contracts without being shown as projected steps.
    """

    workflow_id: str
    version: str
    intent: EntryIntent
    steps: tuple[WorkflowStepSpec, ...]
    projection_policy: ProjectionPolicy = "none"
    hitl_policy: str = "none"
    recovery_policy: str = "branch"

    # NOTE: structural integrity (unique step ids, resolvable dependencies,
    # acyclic graph) is intentionally NOT enforced in ``__post_init__``. It is
    # owned by ``WorkflowSpecValidator`` so all spec validation lives in one
    # place and can report every issue at once instead of raising on the first.

    @property
    def requires_projection(self) -> bool:
        return self.projection_policy == "step_projection"

    @property
    def allows_llm_decision_node(self) -> bool:
        return any(s.llm_decision_node for s in self.steps)

    @property
    def allows_tools(self) -> bool:
        return any(s.tool_name or s.allowed_tools for s in self.steps)

    @property
    def has_high_risk_side_effect(self) -> bool:
        return any(s.risk_level == "high" or "delete_longterm" in s.side_effects for s in self.steps)

    def project(self) -> list[ExecutionStep]:
        """Project this workflow into fresh runtime steps when policy allows it."""
        if not self.requires_projection:
            return []
        return [
            step.to_projection(self.workflow_id, self.version)
            for step in self.steps
            if step.project_to_plan
        ]

    def to_definition_payload(self) -> dict[str, object]:
        """Serialize the workflow contract for deployment/version storage."""
        return {
            "workflow_id": self.workflow_id,
            "version": self.version,
            "intent": self.intent,
            "projection_policy": self.projection_policy,
            "hitl_policy": self.hitl_policy,
            "recovery_policy": self.recovery_policy,
            "steps": [asdict(step) for step in self.steps],
        }

    @classmethod
    def from_definition_payload(cls, payload: dict[str, object]) -> "WorkflowSpec":
        """Restore a workflow contract from the deployment store payload."""
        steps: list[WorkflowStepSpec] = []
        for raw in payload.get("steps") or []:
            if not isinstance(raw, dict):
                continue
            conditional_edges = tuple(
                WorkflowConditionalEdge(
                    condition=str(edge.get("condition", "")),
                    target=str(edge.get("target", "")),
                )
                for edge in (raw.get("conditional_edges") or [])
                if isinstance(edge, dict)
            )
            steps.append(
                WorkflowStepSpec(
                    step_id=str(raw.get("step_id", "")),
                    action_type=str(raw.get("action_type", "")),
                    description=str(raw.get("description", "")),
                    tool_name=raw.get("tool_name") if raw.get("tool_name") is not None else None,
                    tool_input=dict(raw.get("tool_input") or {}),
                    depends_on=tuple(str(item) for item in (raw.get("depends_on") or ())),
                    expected_output=str(raw.get("expected_output", "")),
                    success_criteria=str(raw.get("success_criteria", "")),
                    risk_level=str(raw.get("risk_level", "low")),
                    requires_confirmation=bool(raw.get("requires_confirmation", False)),
                    on_failure=str(raw.get("on_failure", "skip")),
                    execution_mode=str(raw.get("execution_mode", "deterministic")),
                    allowed_tools=tuple(str(item) for item in (raw.get("allowed_tools") or ())),
                    max_iterations=int(raw.get("max_iterations", 3)),
                    llm_decision_node=(
                        str(raw["llm_decision_node"])
                        if raw.get("llm_decision_node") is not None
                        else None
                    ),
                    side_effects=tuple(str(item) for item in (raw.get("side_effects") or ())),
                    hitl_policy=str(raw.get("hitl_policy", "none")),
                    recovery_policy=str(raw.get("recovery_policy", "skip")),
                    branch_policy=str(raw.get("branch_policy", "continue")),
                    conditional_edges=conditional_edges,
                    project_to_plan=bool(raw.get("project_to_plan", True)),
                )
            )
        return cls(
            workflow_id=str(payload.get("workflow_id", "")),
            version=str(payload.get("version", "v1")),
            intent=str(payload.get("intent", "unknown")),
            steps=tuple(steps),
            projection_policy=str(payload.get("projection_policy", "none")),
            hitl_policy=str(payload.get("hitl_policy", "none")),
            recovery_policy=str(payload.get("recovery_policy", "branch")),
        )


class WorkflowRegistryProtocol(Protocol):
    """Structural type for the workflow registry as seen by lower layers.

    The concrete ``WorkflowRegistry`` (with the in-repo flow definitions) lives in
    the planning layer. The infra workflow store only needs to select and list
    specs, so it depends on this Protocol — not the planning class — to avoid an
    upward dependency.
    """

    def select(self, intent: str) -> WorkflowSpec: ...

    def all_specs(self) -> list[WorkflowSpec]: ...


__all__ = [
    "ProjectionPolicy",
    "BranchPolicy",
    "EDGE_END",
    "EDGE_CLARIFY",
    "EDGE_ABORT",
    "EDGE_SENTINELS",
    "WorkflowConditionalEdge",
    "WorkflowStepSpec",
    "WorkflowSpec",
    "WorkflowRegistryProtocol",
]
