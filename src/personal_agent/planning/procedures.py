"""Catalog, applicability, materialization, and runtime for governed procedures."""

from __future__ import annotations

from dataclasses import dataclass, replace

from personal_agent.kernel.contracts.agentic import ExecutionLedger, TaskSpec
from personal_agent.kernel.contracts.capability import CapabilityRequirement
from personal_agent.kernel.contracts.execution import ExecutionStep
from personal_agent.kernel.contracts.procedure import (
    PROCEDURE_SENTINELS,
    ProcedureApplicability,
    ProcedureCall,
    ProcedureCandidate,
    ProcedureCondition,
    ProcedureEvent,
    ProcedureInstance,
    ProcedureNodeSpec,
    ProcedureNodeState,
    ProcedureSpec,
)


class ProcedureDefinitionError(ValueError):
    pass


class ProcedureSpecValidator:
    def validate(self, spec: ProcedureSpec) -> None:
        if not spec.procedure_id or not spec.version or not spec.nodes:
            raise ProcedureDefinitionError("procedure requires identity, version, and nodes")
        node_ids = [node.node_id for node in spec.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ProcedureDefinitionError("procedure node IDs must be unique")
        known = set(node_ids)
        graph: dict[str, set[str]] = {}
        for node in spec.nodes:
            missing = set(node.depends_on) - known
            if missing:
                raise ProcedureDefinitionError(
                    f"procedure node {node.node_id} has unknown dependencies: {sorted(missing)}"
                )
            for edge in node.conditional_edges:
                if edge.target not in known and edge.target not in PROCEDURE_SENTINELS:
                    raise ProcedureDefinitionError(
                        f"procedure node {node.node_id} has unknown edge target {edge.target}"
                    )
            if node.kind == "tool_call" and not (
                node.domain_handler or node.capability_requirement
            ):
                raise ProcedureDefinitionError(
                    f"tool node {node.node_id} needs a domain handler or capability requirement"
                )
            graph[node.node_id] = set(node.depends_on)
        self._validate_acyclic(graph)

    @staticmethod
    def _validate_acyclic(graph: dict[str, set[str]]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ProcedureDefinitionError("procedure dependencies contain a cycle")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in graph[node_id]:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in graph:
            visit(node_id)


class ProcedureCatalog:
    def __init__(self, specs: tuple[ProcedureSpec, ...]) -> None:
        validator = ProcedureSpecValidator()
        self._specs: dict[tuple[str, str], ProcedureSpec] = {}
        self._latest: dict[str, ProcedureSpec] = {}
        for spec in specs:
            validator.validate(spec)
            key = (spec.procedure_id, spec.version)
            if key in self._specs:
                raise ProcedureDefinitionError(f"duplicate procedure definition: {key}")
            self._specs[key] = spec
            self._latest[spec.procedure_id] = spec

    def get(self, procedure_id: str, version: str | None = None) -> ProcedureSpec:
        spec = self._latest.get(procedure_id) if version is None else self._specs.get((procedure_id, version))
        if spec is None:
            raise KeyError(f"unknown procedure: {procedure_id}@{version or 'latest'}")
        return spec

    def all_specs(self) -> tuple[ProcedureSpec, ...]:
        return tuple(self._specs.values())


class ProcedureApplicabilityResolver:
    """Specification-based filter over structured task state."""

    def __init__(self, catalog: ProcedureCatalog) -> None:
        self._catalog = catalog

    def resolve(self, task: TaskSpec, ledger: ExecutionLedger) -> tuple[ProcedureCandidate, ...]:
        candidates: list[ProcedureCandidate] = []
        for goal in ledger.items:
            if goal.status in {"verified", "degraded", "abandoned"}:
                continue
            resources = tuple(
                item for item in task.resource_requirements
                if item.goal_id in {"", goal.goal_id}
            )
            for spec in self._catalog.all_specs():
                candidates.append(self._evaluate(spec, goal.goal_id, resources))
        return tuple(candidates)

    @staticmethod
    def _evaluate(spec: ProcedureSpec, goal_id: str, resources) -> ProcedureCandidate:
        applicability = spec.applicability
        domains = {item.semantic_domain for item in resources}
        resource_types = {value for item in resources for value in item.resource_types}
        operations = {value for item in resources for value in item.required_operations}
        reasons: list[str] = []
        matched: list[str] = []
        if applicability.semantic_domains and not domains.intersection(applicability.semantic_domains):
            reasons.append("semantic_domain")
        else:
            matched.append("semantic_domain")
        if applicability.resource_types and not resource_types.intersection(applicability.resource_types):
            reasons.append("resource_type")
        elif applicability.resource_types:
            matched.append("resource_type")
        if applicability.operations and not operations.intersection(applicability.operations):
            reasons.append("operation")
        elif applicability.operations:
            matched.append("operation")
        status = "ineligible" if reasons else ("mandatory" if applicability.mandatory else "eligible")
        side_effects = {
            effect for node in spec.nodes for effect in node.side_effects if effect != "none"
        }
        return ProcedureCandidate(
            procedure_id=spec.procedure_id,
            version=spec.version,
            goal_id=goal_id,
            purpose=spec.purpose,
            status=status,
            matched_requirements=tuple(matched),
            rejected_reasons=tuple(reasons),
            side_effect_class=next(iter(sorted(side_effects)), "none"),
            requires_confirmation=spec.confirmation_policy != "none",
        )


@dataclass(frozen=True, slots=True)
class MaterializedProcedure:
    call: ProcedureCall
    spec: ProcedureSpec
    instance: ProcedureInstance
    steps: tuple[ExecutionStep, ...]


class ProcedureMaterializer:
    def __init__(self, catalog: ProcedureCatalog) -> None:
        self._catalog = catalog

    def materialize(self, call: ProcedureCall, *, task_id: str) -> MaterializedProcedure:
        spec = self._catalog.get(call.procedure_id, call.procedure_version)
        nodes = self._adapt_nodes(spec, call)
        steps = tuple(node.to_execution_step(spec.procedure_id, spec.version, call.goal_id) for node in nodes)
        step_ids = {
            node.node_id: f"{call.procedure_call_id}:{node.node_id}" for node in nodes
        }
        task_input = str(call.input.get("text") or "")
        for step in steps:
            step.step_id = step_ids[step.procedure_node_id]
            step.depends_on = [step_ids[node_id] for node_id in step.depends_on]
            step.task_input = task_input
            if (
                spec.procedure_id == "knowledge_ingest"
                and step.tool_name == "capture_text"
                and not step.depends_on
            ):
                step.tool_input.update({"text": task_input, "source_type": "text"})
        instance = ProcedureInstance(
            procedure_id=spec.procedure_id,
            version=spec.version,
            task_id=task_id,
            goal_id=call.goal_id,
            input=call.input,
            active_node_ids=tuple(
                node.node_id for node in nodes if not node.depends_on
            ),
            node_states=tuple(ProcedureNodeState(node_id=node.node_id) for node in nodes),
        )
        return MaterializedProcedure(call, spec, instance, steps)

    @staticmethod
    def _adapt_nodes(spec: ProcedureSpec, call: ProcedureCall) -> tuple[ProcedureNodeSpec, ...]:
        if spec.procedure_id == "research_run" and call.input.get("locator"):
            return tuple(
                replace(node, depends_on=()) if node.node_id == "initialize" else node
                for node in spec.nodes if node.node_id != "prepare"
            )
        if spec.procedure_id != "knowledge_ingest":
            return spec.nodes
        resource_types = {str(item) for item in call.input.get("resource_types", [])}
        if not resource_types.intersection({"url", "link", "file", "artifact", "document"}):
            return tuple(
                replace(node, depends_on=()) if node.node_id == "ingest" else node
                for node in spec.nodes if node.node_id != "acquire-source"
            )
        acquire_domain = "web" if resource_types.intersection({"url", "link"}) else "artifact"
        acquire = next(node for node in spec.nodes if node.node_id == "acquire-source")
        requirement = acquire.capability_requirement
        assert requirement is not None
        adapted = replace(acquire, capability_requirement=requirement.model_copy(update={
            "semantic_domains": (acquire_domain,),
            "resource_types": tuple(sorted(resource_types)),
            "resource_locator": str(call.input.get("locator") or "") or None,
        }))
        return tuple(adapted if node.node_id == "acquire-source" else node for node in spec.nodes)


class ProcedureEventProjector:
    def project(self, instance: ProcedureInstance, events: tuple[ProcedureEvent, ...]) -> ProcedureInstance:
        current = instance
        node_states = {item.node_id: item for item in current.node_states}
        for event in sorted(events, key=lambda item: item.sequence):
            if event.event_type == "procedure_started":
                current = current.model_copy(update={"status": "running"})
            elif event.node_id and event.event_type in {"node_started", "node_completed", "node_failed"}:
                status = {
                    "node_started": "running", "node_completed": "completed", "node_failed": "failed",
                }[event.event_type]
                node = node_states[event.node_id]
                node_states[event.node_id] = node.model_copy(update={
                    "status": status,
                    "attempt_count": node.attempt_count + (1 if status == "running" else 0),
                })
            elif event.event_type == "confirmation_requested":
                current = current.model_copy(update={"status": "awaiting_confirmation"})
            elif event.event_type == "procedure_completed":
                current = current.model_copy(update={"status": "completed"})
            elif event.event_type == "procedure_degraded":
                current = current.model_copy(update={"status": "degraded"})
            elif event.event_type == "procedure_failed":
                current = current.model_copy(update={"status": "failed"})
        return current.model_copy(update={"node_states": tuple(node_states.values())})


class ProcedureRuntime:
    """State-machine facade; LangGraph executes the materialized node projections."""

    def __init__(self, materializer: ProcedureMaterializer) -> None:
        self._materializer = materializer
        self._projector = ProcedureEventProjector()

    def start(self, call: ProcedureCall, *, task_id: str) -> MaterializedProcedure:
        materialized = self._materializer.materialize(call, task_id=task_id)
        event = ProcedureEvent(
            sequence=1,
            procedure_run_id=materialized.instance.procedure_run_id,
            event_type="procedure_started",
            payload={"procedure_id": call.procedure_id, "version": call.procedure_version},
        )
        instance = self._projector.project(materialized.instance, (event,))
        return MaterializedProcedure(call, materialized.spec, instance, materialized.steps)


def _requirement(
    requirement_id: str,
    purpose: str,
    domains: tuple[str, ...],
    resources: tuple[str, ...],
    operations: tuple[str, ...],
    output_contract: str,
) -> CapabilityRequirement:
    return CapabilityRequirement(
        requirement_id=requirement_id,
        purpose=purpose,
        semantic_domains=domains,
        resource_types=resources,
        operations=operations,
        output_contract=output_contract,
    )


def _catalog() -> ProcedureCatalog:
    return ProcedureCatalog((
        ProcedureSpec(
            procedure_id="knowledge_ingest",
            version="1",
            purpose="Acquire an optional source and admit it into durable knowledge.",
            applicability=ProcedureApplicability(
                semantic_domains=("knowledge", "web", "artifact"),
                resource_types=("note", "text", "message", "document", "url", "link", "file", "artifact"),
                operations=("ingest", "create"),
                mandatory=True,
            ),
            nodes=(
                ProcedureNodeSpec(
                    node_id="acquire-source",
                    kind="tool_call",
                    description="Acquire source content using an eligible provider.",
                    capability_requirement=_requirement(
                        "ingest-source", "Acquire source content", ("artifact",),
                        ("document",), ("read",), "FetchedDocument",
                    ),
                    recovery_policy="clarify",
                ),
                ProcedureNodeSpec(
                    node_id="ingest",
                    kind="tool_call",
                    description="Admit normalized content into durable knowledge.",
                    depends_on=("acquire-source",),
                    domain_handler="capture_text",
                    side_effects=("write_longterm",),
                    recovery_policy="abort",
                ),
            ),
            invariants=("durable admission", "idempotent mutation receipt"),
            confirmation_policy="required",
            recovery_policy="checkpoint_node",
        ),
        ProcedureSpec(
            procedure_id="knowledge_delete",
            version="1",
            purpose="Resolve, confirm, delete, and audit durable knowledge.",
            applicability=ProcedureApplicability(
                semantic_domains=("knowledge",), resource_types=("note", "knowledge"),
                operations=("delete",), mandatory=True,
            ),
            nodes=(
                ProcedureNodeSpec(
                    "resolve-candidates", "retrieve", "Find deletion candidates.",
                    execution_mode="deterministic",
                    capability_requirement=_requirement(
                        "delete-candidates", "Find candidate knowledge", ("knowledge",),
                        ("note",), ("search", "read"), "DeletionCandidates",
                    ),
                    recovery_policy="clarify",
                    conditional_edges=(ProcedureCondition("no_candidate", "clarify"),),
                ),
                ProcedureNodeSpec(
                    "resolve-target", "resolve", "Resolve the exact deletion target.",
                    depends_on=("resolve-candidates",), llm_decision_node="delete_target_resolve",
                    recovery_policy="clarify",
                ),
                ProcedureNodeSpec(
                    "commit-delete", "tool_call", "Confirm and delete the selected knowledge.",
                    depends_on=("resolve-target",), domain_handler="delete_note",
                    risk_level="high", requires_confirmation=True, side_effects=("delete_longterm",),
                    hitl_policy="required", recovery_policy="abort",
                ),
                ProcedureNodeSpec(
                    "summarize-delete", "compose", "Summarize the deletion outcome.",
                    depends_on=("commit-delete",),
                ),
            ),
            invariants=("exact target", "confirmation", "deletion receipt", "audit"),
            confirmation_policy="required",
            recovery_policy="checkpoint_node",
        ),
        ProcedureSpec(
            procedure_id="conversation_solidify",
            version="1",
            purpose="Convert a selected conversation scope into admitted knowledge.",
            applicability=ProcedureApplicability(
                semantic_domains=("conversation", "knowledge"),
                resource_types=("conversation", "thread"), operations=("ingest",), mandatory=True,
            ),
            nodes=(
                ProcedureNodeSpec(
                    "draft", "compose", "Create an admissible knowledge draft from the conversation.",
                    llm_decision_node="solidify_draft", recovery_policy="abort",
                ),
                ProcedureNodeSpec(
                    "ingest", "tool_call", "Admit the conversation draft into durable knowledge.",
                    depends_on=("draft",), domain_handler="capture_text",
                    side_effects=("write_longterm",), recovery_policy="abort",
                ),
            ),
            invariants=("selected scope", "confirmation", "durable admission"),
            confirmation_policy="required",
            recovery_policy="checkpoint_node",
        ),
        ProcedureSpec(
            procedure_id="knowledge_consolidate",
            version="1",
            purpose="Consolidate related knowledge and record supersession relationships.",
            applicability=ProcedureApplicability(
                semantic_domains=("knowledge",), resource_types=("note", "knowledge"),
                operations=("repair",), mandatory=True,
            ),
            nodes=(ProcedureNodeSpec(
                "consolidate", "tool_call", "Consolidate selected knowledge.",
                domain_handler="consolidate_knowledge", side_effects=("write_longterm",),
                recovery_policy="abort",
            ),),
            invariants=("provenance preserved", "supersession recorded", "mutation receipt"),
            confirmation_policy="required",
        ),
        ProcedureSpec(
            procedure_id="research_run",
            version="1",
            purpose="Run durable evidence-driven research with checkpoints and verification.",
            applicability=ProcedureApplicability(
                semantic_domains=("external_research", "research"),
                resource_types=("research", "report", "evidence"),
                operations=("search", "read", "verify"),
            ),
            nodes=(
                ProcedureNodeSpec(
                    "prepare", "tool_call", "Create the durable research run.",
                    domain_handler="research_prepare_run", side_effects=("write_longterm",),
                    recovery_policy="abort",
                ),
                ProcedureNodeSpec(
                    "initialize", "tool_call", "Initialize evidence-driven research state.",
                    depends_on=("prepare",), domain_handler="research_initialize_state",
                    side_effects=("write_longterm",), recovery_policy="abort",
                ),
                ProcedureNodeSpec(
                    "research-loop", "tool_call", "Explore based on current evidence gaps.",
                    depends_on=("initialize",), domain_handler="research_run_loop",
                    side_effects=("external_network", "write_longterm"), recovery_policy="abort",
                ),
                ProcedureNodeSpec(
                    "synthesize", "tool_call", "Synthesize a research digest.",
                    depends_on=("research-loop",), domain_handler="research_synthesize_digest",
                    side_effects=("write_longterm",), recovery_policy="abort",
                ),
                ProcedureNodeSpec(
                    "verify", "tool_call", "Verify digest evidence coverage.",
                    depends_on=("synthesize",), domain_handler="research_verify_digest",
                    side_effects=("write_longterm",), recovery_policy="abort",
                ),
                ProcedureNodeSpec("present", "compose", "Present the verified research result.", depends_on=("verify",)),
            ),
            invariants=("budget", "evidence loop", "checkpoint", "verification"),
            recovery_policy="checkpoint_node",
            evidence_required=True,
        ),
        ProcedureSpec(
            procedure_id="research_subscription_create",
            version="1",
            purpose="Create a durable scheduled research subscription.",
            applicability=ProcedureApplicability(
                semantic_domains=("external_research", "research"),
                resource_types=("subscription",), operations=("create",), mandatory=True,
            ),
            nodes=(ProcedureNodeSpec(
                "create-subscription", "tool_call", "Create the research subscription.",
                domain_handler="create_research_subscription", risk_level="medium",
                side_effects=("write_longterm",), recovery_policy="abort",
            ),),
            invariants=("durable schedule", "idempotent create", "audit"),
            confirmation_policy="required",
        ),
    ))


PROCEDURE_CATALOG = _catalog()


__all__ = [
    "MaterializedProcedure", "PROCEDURE_CATALOG", "ProcedureApplicabilityResolver",
    "ProcedureCatalog", "ProcedureDefinitionError", "ProcedureEventProjector",
    "ProcedureMaterializer", "ProcedureRuntime", "ProcedureSpecValidator",
]
