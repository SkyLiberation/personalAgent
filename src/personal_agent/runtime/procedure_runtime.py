"""Catalog, applicability, materialization, and runtime for governed procedures."""

from __future__ import annotations

from dataclasses import dataclass, replace

from personal_agent.runtime.contracts.task import (
    TaskRuntimeProjection,
    TaskContract,
    materialize_goals,
)
from personal_agent.capabilities.contracts.execution import CapabilityRequirement
from personal_agent.execution.contracts.invocation import (
    ConditionalTransition,
    ExecutableInvocation,
    ProcedureNodeInvocation,
)
from personal_agent.capabilities.contracts.procedure import (
    PROCEDURE_SENTINELS,
    ProcedureApplicability,
    ProcedureInvocation,
    ProcedureCandidate,
    ProcedureEvent,
    ProcedureRunProjection,
    ProcedureNodeSpec,
    ProcedureNodeState,
    ProcedureDefinition,
    KnowledgeIngestInput,
    ResearchRunInput,
)


class ProcedureDefinitionError(ValueError):
    pass


class ProcedureSpecValidator:
    def validate(self, spec: ProcedureDefinition) -> None:
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
    def __init__(self, specs: tuple[ProcedureDefinition, ...]) -> None:
        validator = ProcedureSpecValidator()
        self._specs: dict[tuple[str, str], ProcedureDefinition] = {}
        self._latest: dict[str, ProcedureDefinition] = {}
        for spec in specs:
            validator.validate(spec)
            key = (spec.procedure_id, spec.version)
            if key in self._specs:
                raise ProcedureDefinitionError(f"duplicate procedure definition: {key}")
            self._specs[key] = spec
            self._latest[spec.procedure_id] = spec

    def get(self, procedure_id: str, version: str | None = None) -> ProcedureDefinition:
        spec = self._latest.get(procedure_id) if version is None else self._specs.get((procedure_id, version))
        if spec is None:
            raise KeyError(f"unknown procedure: {procedure_id}@{version or 'latest'}")
        return spec

    def all_specs(self) -> tuple[ProcedureDefinition, ...]:
        return tuple(self._specs.values())


class ProcedureApplicabilityResolver:
    """Specification-based filter over structured task state."""

    def __init__(self, catalog: ProcedureCatalog) -> None:
        self._catalog = catalog

    def resolve(self, task: TaskContract, ledger: TaskRuntimeProjection) -> tuple[ProcedureCandidate, ...]:
        candidates: list[ProcedureCandidate] = []
        for goal in materialize_goals(task, ledger):
            if goal.status in {"verified", "degraded", "abandoned"}:
                continue
            resources = task.resources_for_goal(goal.goal_id)
            for spec in self._catalog.all_specs():
                candidates.append(self._evaluate(spec, goal.goal_id, resources))
        return tuple(candidates)

    @staticmethod
    def _evaluate(spec: ProcedureDefinition, goal_id: str, resources) -> ProcedureCandidate:
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
    invocation: ProcedureInvocation
    definition: ProcedureDefinition
    projection: ProcedureRunProjection
    steps: tuple[ExecutableInvocation, ...]


class ProcedureMaterializer:
    def __init__(self, catalog: ProcedureCatalog) -> None:
        self._catalog = catalog

    def materialize(self, invocation: ProcedureInvocation) -> MaterializedProcedure:
        definition = self._catalog.get(
            invocation.procedure.procedure_id,
            invocation.procedure.version,
        )
        nodes = self._adapt_nodes(definition, invocation)
        steps = tuple(
            _node_to_invocation(
                node, definition.procedure_id, definition.version, invocation.goal_id,
            )
            for node in nodes
        )
        step_ids = {
            node.node_id: f"{invocation.invocation_id}:{node.node_id}" for node in nodes
        }
        task_input = _procedure_task_input(invocation)
        for step in steps:
            step.step_id = step_ids[step.procedure_node_id]
            step.depends_on = [step_ids[node_id] for node_id in step.depends_on]
            step.task_input = task_input
            if (
                isinstance(invocation.input, KnowledgeIngestInput)
                and step.tool_name == "capture_url"
                and invocation.input.locator is not None
            ):
                # Decision Ownership Taxonomy: deterministic parameter
                # compilation from the accepted canonical locator. Parsing the
                # task description here would create a second identity source.
                step.tool_input["url"] = invocation.input.locator
            if (
                definition.procedure_id == "knowledge_ingest"
                and step.tool_name == "capture_text"
                and not step.depends_on
            ):
                step.tool_input.update({"text": task_input, "source_type": "text"})
        projection = ProcedureRunProjection(
            invocation_id=invocation.invocation_id,
            procedure=invocation.procedure,
            active_node_ids=tuple(
                node.node_id for node in nodes if not node.depends_on
            ),
            node_states=tuple(ProcedureNodeState(node_id=node.node_id) for node in nodes),
        )
        return MaterializedProcedure(invocation, definition, projection, steps)

    @staticmethod
    def _adapt_nodes(
        definition: ProcedureDefinition,
        invocation: ProcedureInvocation,
    ) -> tuple[ProcedureNodeSpec, ...]:
        if (
            definition.procedure_id == "research_run"
            and isinstance(invocation.input, ResearchRunInput)
            and invocation.input.locator
        ):
            return tuple(
                replace(node, depends_on=()) if node.node_id == "initialize" else node
                for node in definition.nodes if node.node_id != "prepare"
            )
        if definition.procedure_id != "knowledge_ingest":
            return definition.nodes
        if not isinstance(invocation.input, KnowledgeIngestInput):
            raise ProcedureDefinitionError("knowledge_ingest requires KnowledgeIngestInput")
        resource_types = set(invocation.input.resource_types)
        if not resource_types.intersection({"url", "link", "file", "artifact", "document"}):
            return tuple(
                replace(node, depends_on=()) if node.node_id == "ingest" else node
                for node in definition.nodes if node.node_id != "acquire-source"
            )
        is_web_source = bool(resource_types.intersection({"url", "link"}))
        acquire_domain = "web" if is_web_source else "artifact"
        domain_handler = "capture_url" if is_web_source else "inspect_artifact"
        # Decision Ownership Taxonomy: deterministic capability-contract
        # projection. The accepted resource type selects the unique built-in
        # reader contract, including its declared technical side-effect class;
        # no target, payload, or provider is introduced here.
        side_effect_class = "external_network" if is_web_source else "none"
        acquire = next(node for node in definition.nodes if node.node_id == "acquire-source")
        requirement = acquire.capability_requirement
        assert requirement is not None
        adapted = replace(
            acquire,
            domain_handler=domain_handler,
            capability_requirement=CapabilityRequirement.from_dimensions(
                requirement_id=requirement.requirement_id,
                purpose=requirement.purpose,
                semantic_domains=(acquire_domain,),
                resource_types=tuple(sorted(resource_types)),
                operations=("read",),
                resource_locator=invocation.input.locator,
                output_contract="ToolResult",
                side_effect_class=side_effect_class,
            ),
        )
        return tuple(
            adapted if node.node_id == "acquire-source" else node
            for node in definition.nodes
        )


def _node_to_invocation(
    node: ProcedureNodeSpec,
    procedure_id: str,
    version: str,
    goal_id: str,
) -> ExecutableInvocation:
    requirement = node.capability_requirement
    return ExecutableInvocation(
        step_id=node.node_id,
        action_type=node.kind,
        description=node.description,
        tool_name=node.domain_handler,
        tool_input=dict(node.handler_input),
        depends_on=list(node.depends_on),
        expected_output=node.expected_output,
        success_criteria=node.success_criteria,
        risk_level=node.risk_level,
        requires_confirmation=node.requires_confirmation,
        on_failure=node.on_failure,
        execution_mode=node.execution_mode,
        max_iterations=node.max_iterations,
        llm_decision_node=node.llm_decision_node or "",
        procedure=ProcedureNodeInvocation(
            procedure_id=procedure_id,
            procedure_version=version,
            node_id=node.node_id,
            recovery_policy=node.recovery_policy,
            branch_policy=node.branch_policy,
            transitions=tuple(
                ConditionalTransition(condition=edge.condition, target=edge.target)
                for edge in node.conditional_edges
            ),
        ),
        projection_kind="procedure_node",
        goal_id=goal_id,
        execution_intent="commit" if node.side_effects else node.kind,
        output_contract=requirement.output_contract if requirement else "ToolResult",
        capability_requirements=[requirement] if requirement is not None else [],
    )


def _procedure_task_input(invocation: ProcedureInvocation) -> str:
    value = invocation.input
    if isinstance(value, KnowledgeIngestInput):
        return value.text
    if isinstance(value, ResearchRunInput):
        return value.question
    if hasattr(value, "target_ref"):
        return str(value.target_ref)
    if hasattr(value, "target_refs"):
        return "\n".join(value.target_refs)
    if hasattr(value, "conversation_scope_ref"):
        return str(value.conversation_scope_ref)
    if hasattr(value, "question"):
        return str(value.question)
    raise ProcedureDefinitionError(f"unsupported procedure input: {value.kind}")


class ProcedureEventProjector:
    def project(self, instance: ProcedureRunProjection, events: tuple[ProcedureEvent, ...]) -> ProcedureRunProjection:
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

    def start(self, invocation: ProcedureInvocation) -> MaterializedProcedure:
        materialized = self._materializer.materialize(invocation)
        event = ProcedureEvent(
            sequence=1,
            procedure_run_id=materialized.projection.procedure_run_id,
            event_type="procedure_started",
            payload={
                "procedure_id": invocation.procedure.procedure_id,
                "version": invocation.procedure.version,
            },
        )
        projection = self._projector.project(materialized.projection, (event,))
        return MaterializedProcedure(
            invocation,
            materialized.definition,
            projection,
            materialized.steps,
        )


def _requirement(
    requirement_id: str,
    purpose: str,
    domains: tuple[str, ...],
    resources: tuple[str, ...],
    operations: tuple[str, ...],
    output_contract: str,
) -> CapabilityRequirement:
    return CapabilityRequirement.from_dimensions(
        requirement_id=requirement_id,
        purpose=purpose,
        semantic_domains=domains,
        resource_types=resources,
        operations=operations,
        output_contract=output_contract,
    )


def _catalog() -> ProcedureCatalog:
    return ProcedureCatalog((
        ProcedureDefinition(
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
                    capability_requirement=_requirement(
                        "ingest-commit", "Persist normalized knowledge",
                        ("capture", "knowledge_lifecycle"), ("text", "note"),
                        ("ingest", "create"), "ToolResult",
                    ),
                    side_effects=("write_longterm",),
                    recovery_policy="abort",
                ),
            ),
            invariants=("durable admission", "idempotent mutation receipt"),
            confirmation_policy="required",
            recovery_policy="checkpoint_node",
        ),
        ProcedureDefinition(
            procedure_id="knowledge_delete",
            version="1",
            purpose="Resolve, confirm, delete, and audit durable knowledge.",
            applicability=ProcedureApplicability(
                semantic_domains=("knowledge",), resource_types=("note", "knowledge"),
                operations=("delete",), mandatory=True,
            ),
            nodes=(
                ProcedureNodeSpec(
                    "resolve-target", "resolve", "Validate the user-grounded canonical deletion target.",
                    recovery_policy="clarify",
                ),
                ProcedureNodeSpec(
                    "commit-delete", "tool_call", "Confirm and delete the selected knowledge.",
                    depends_on=("resolve-target",), domain_handler="delete_note",
                    capability_requirement=_requirement(
                        "delete-commit", "Delete the exact knowledge target",
                        ("knowledge", "knowledge_lifecycle"), ("note",),
                        ("delete",), "MutationReceipt",
                    ),
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
        ProcedureDefinition(
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
                    capability_requirement=_requirement(
                        "conversation-ingest", "Persist the admitted conversation draft",
                        ("capture", "knowledge_lifecycle"), ("text", "note"),
                        ("ingest", "create"), "MutationReceipt",
                    ),
                    side_effects=("write_longterm",), recovery_policy="abort",
                ),
            ),
            invariants=("selected scope", "confirmation", "durable admission"),
            confirmation_policy="required",
            recovery_policy="checkpoint_node",
        ),
        ProcedureDefinition(
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
                capability_requirement=_requirement(
                    "knowledge-consolidate", "Consolidate admitted knowledge",
                    ("knowledge", "knowledge_lifecycle"), ("note",),
                    ("repair", "update"), "MutationReceipt",
                ),
                recovery_policy="abort",
            ),),
            invariants=("provenance preserved", "supersession recorded", "mutation receipt"),
            confirmation_policy="required",
        ),
        ProcedureDefinition(
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
                    capability_requirement=_requirement(
                        "research-prepare", "Create a durable research run",
                        ("research",), ("research",), ("create",), "ToolResult",
                    ),
                    recovery_policy="abort",
                ),
                ProcedureNodeSpec(
                    "initialize", "tool_call", "Initialize evidence-driven research state.",
                    depends_on=("prepare",), domain_handler="research_initialize_state",
                    capability_requirement=_requirement(
                        "research-initialize", "Initialize research state",
                        ("research",), ("research",), ("update",), "ToolResult",
                    ),
                    side_effects=("write_longterm",), recovery_policy="abort",
                ),
                ProcedureNodeSpec(
                    "research-loop", "tool_call", "Explore based on current evidence gaps.",
                    depends_on=("initialize",), domain_handler="research_run_loop",
                    capability_requirement=_requirement(
                        "research-loop", "Acquire research evidence",
                        ("research", "external_research"), ("evidence",),
                        ("search", "read", "update"), "EvidencePack",
                    ),
                    side_effects=("external_network", "write_longterm"), recovery_policy="abort",
                ),
                ProcedureNodeSpec(
                    "synthesize", "tool_call", "Synthesize a research digest.",
                    depends_on=("research-loop",), domain_handler="research_synthesize_digest",
                    capability_requirement=_requirement(
                        "research-synthesize", "Synthesize the research digest",
                        ("research",), ("report",), ("update",), "ResearchDigest",
                    ),
                    side_effects=("write_longterm",), recovery_policy="abort",
                ),
                ProcedureNodeSpec(
                    "verify", "tool_call", "Verify digest evidence coverage.",
                    depends_on=("synthesize",), domain_handler="research_verify_digest",
                    capability_requirement=_requirement(
                        "research-verify", "Verify research evidence coverage",
                        ("research",), ("report", "evidence"),
                        ("verify", "update"), "GoalVerificationReport",
                    ),
                    side_effects=("write_longterm",), recovery_policy="abort",
                ),
                ProcedureNodeSpec("present", "compose", "Present the verified research result.", depends_on=("verify",)),
            ),
            invariants=("budget", "evidence loop", "checkpoint", "verification"),
            recovery_policy="checkpoint_node",
            evidence_required=True,
        ),
        ProcedureDefinition(
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
                capability_requirement=_requirement(
                    "subscription-create", "Create a research subscription",
                    ("research",), ("subscription",), ("create",), "MutationReceipt",
                ),
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
