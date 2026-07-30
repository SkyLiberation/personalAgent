"""Structured-model implementations of Project semantic decision ports."""

from __future__ import annotations

from datetime import date
import json
import re
from typing import Annotated, Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    create_model,
    field_validator,
    model_validator,
)

from personal_agent.application.investigation_project.admission import (
    execution_evidence_subgoal_keys,
    frozen_subgoal_keys,
    observed_url_locators,
    repair_subgoal_logical_id,
    subgoal_definition_digest,
    unverified_tool_execution_operations,
)
from personal_agent.application.investigation_project.capability_matching import (
    matching_execution_inventory,
)
from personal_agent.application.investigation_project.ports import (
    EvidenceMaterial,
    FinalVerificationResult,
    GeneratedContent,
    ModelDecision,
)
from personal_agent.capabilities.contracts.model import (
    StructuredModelClient,
    StructuredModelRequest,
    sealed_context_projection_ref,
)
from personal_agent.capabilities.inventory import RuntimeCapabilityInventory
from personal_agent.domain.investigation_project import (
    AgentExecutionOperation,
    CapabilityContract,
    DerivedRequirement,
    InvestigationProject,
    InvestigationProjectDefinition,
    PlanAssumption,
    PlanProposal,
    ProjectUsage,
    ReplanRequest,
    RequirementMapping,
    SubGoalDefinitionVersion,
    SubGoalExecutionProposal,
    SubGoalVersionRef,
    SubGoalVerificationAssessment,
    SynthesisOperation,
    ToolExecutionOperation,
    UserInputOperation,
    canonical_digest,
    new_proposal_id,
)
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import ExecutionScope


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _SubGoalDraft(_Model):
    logical_subgoal_id: str
    objective: str
    depends_on: tuple[str, ...] = ()
    required_output: str
    capability_contract: CapabilityContract

    @field_validator("capability_contract")
    @classmethod
    def _exclude_project_verification_work(
        cls,
        value: CapabilityContract,
    ) -> CapabilityContract:
        if value.semantic_domain.strip().lower() in {
            "verification",
            "semantic_verification",
        }:
            raise ValueError(
                "Project semantic verification is automatic; emit a user-visible "
                "analysis or report synthesis SubGoal instead"
            )
        return value


class _DerivedRequirementDraft(_Model):
    requirement_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    acceptance_contract: str = Field(min_length=1)
    completion_relevance: Literal["required", "informational"] = "required"
    mapped_logical_subgoal_ids: tuple[str, ...] = Field(min_length=1)


class _PlanDraft(_Model):
    assumptions: tuple[PlanAssumption, ...] = ()
    derived_requirements: tuple[_DerivedRequirementDraft, ...] = ()
    subgoals: tuple[_SubGoalDraft, ...]
    requirement_mappings: tuple[RequirementMapping, ...]


class _PlanRevisionDraft(_Model):
    """Semantic changes only; frozen SubGoals are not model-writable fields."""

    assumptions: tuple[PlanAssumption, ...] = ()
    derived_requirements: tuple[_DerivedRequirementDraft, ...] = ()
    revisable_subgoals: tuple[_SubGoalDraft, ...] = ()
    requirement_mappings: tuple[RequirementMapping, ...]


class _IndependentRepairSubGoalDraft(_SubGoalDraft):
    depends_on: tuple[str, ...] = Field(default=(), max_length=0)
    repairs_frozen_logical_subgoal_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=1,
    )


class _RepairPlanRevisionDraft(_Model):
    assumptions: tuple[PlanAssumption, ...] = ()
    derived_requirements: tuple[_DerivedRequirementDraft, ...] = ()
    revisable_subgoals: tuple[_SubGoalDraft, ...] = ()
    independent_repair_subgoals: tuple[
        _IndependentRepairSubGoalDraft,
        ...,
    ] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_one_unique_repair_per_gap(self) -> "_RepairPlanRevisionDraft":
        logical_ids = [
            item.logical_subgoal_id
            for item in self.independent_repair_subgoals
        ]
        repaired_ids = [
            item.repairs_frozen_logical_subgoal_ids[0]
            for item in self.independent_repair_subgoals
        ]
        if len(logical_ids) != len(set(logical_ids)):
            raise ValueError("repair logical subgoal ids must be unique")
        if len(repaired_ids) != len(set(repaired_ids)):
            raise ValueError("each frozen gap must have exactly one repair subgoal")
        return self


class _ToolOperationDraft(_Model):
    kind: Literal["tool"]
    tool_name: str
    typed_arguments: dict[str, Any]
    expected_artifact_type: str


class _AgentOperationDraft(_Model):
    kind: Literal["agent"]
    agent_id: str
    bounded_sub_goal: str
    context_artifact_refs: tuple[ResourceRef, ...] = ()
    expected_artifact_types: tuple[str, ...]
    token_budget: int = Field(ge=0)
    cost_budget: float = Field(ge=0)
    time_budget_seconds: int = Field(ge=1)


class _SynthesisOperationDraft(_Model):
    kind: Literal["synthesis"]
    input_artifact_refs: tuple[ResourceRef, ...] = ()
    requirement_refs: tuple[str, ...]
    output_contract: str


class _UserInputOperationDraft(_Model):
    kind: Literal["user_input"]
    question: str
    required_fields: tuple[str, ...] = ()


_OperationDraft = Annotated[
    _ToolOperationDraft
    | _AgentOperationDraft
    | _SynthesisOperationDraft
    | _UserInputOperationDraft,
    Field(discriminator="kind"),
]


class _ExecutionDraft(_Model):
    operation: _OperationDraft


def _execution_output_type(
    inventory: RuntimeCapabilityInventory,
    subgoal: SubGoalDefinitionVersion,
    *,
    observed_url_locators: tuple[str, ...] = (),
    excluded_tool_operations: tuple[ToolExecutionOperation, ...] = (),
) -> type[BaseModel]:
    matching = matching_execution_inventory(
        inventory,
        subgoal.capability_contract,
    )
    operation_types: list[type[BaseModel]] = []
    tool_names = tuple(dict.fromkeys((
        *(item.tool_name for item in matching.local_tools),
        *(item.local_tool_name for item in matching.mcp_connectors),
    )))
    if "tool" in subgoal.capability_contract.allowed_execution_kinds and tool_names:
        tool_name_type = Literal.__getitem__(tool_names)
        operation_fields: dict[str, tuple[Any, Any]] = {
            "tool_name": (tool_name_type, ...),
        }
        if tool_names == ("capture_url",) and observed_url_locators:
            candidate_ids = tuple(
                f"url_candidate_{index:02d}"
                for index in range(1, len(observed_url_locators) + 1)
            )
            candidate_id_type = Literal.__getitem__(candidate_ids)
            arguments_type = create_model(
                "_CaptureUrlArgumentsWithObservedCandidate",
                __base__=_Model,
                candidate_id=(candidate_id_type, ...),
            )
            operation_fields["typed_arguments"] = (arguments_type, ...)
        elif tool_names == ("web_search",):
            excluded_queries = {
                str(item.typed_arguments.get("query"))
                for item in excluded_tool_operations
                if (
                    item.tool_name == "web_search"
                    and item.typed_arguments.get("query")
                )
            }

            @field_validator("query")
            @classmethod
            def _exclude_previously_failed_query(
                cls,
                value: str,
            ) -> str:
                if value in excluded_queries:
                    raise ValueError(
                        "query exactly repeats a previously failed web_search; "
                        "change its terms or source scope"
                    )
                return value

            arguments_type = create_model(
                "_InvestigationWebSearchArguments",
                __base__=_Model,
                __validators__={
                    "exclude_previously_failed_query": (
                        _exclude_previously_failed_query
                    ),
                },
                query=(str, Field(min_length=1, max_length=400)),
                limit=(Literal[10], 10),
                scrape=(bool, True),
            )
            operation_fields["typed_arguments"] = (arguments_type, ...)
        operation_types.append(create_model(
            "_ToolOperationWithAdmittedCapability",
            __base__=_ToolOperationDraft,
            **operation_fields,
        ))
    agent_ids = tuple(dict.fromkeys(
        item.agent_id for item in matching.a2a_agents
    ))
    if "agent" in subgoal.capability_contract.allowed_execution_kinds and agent_ids:
        agent_id_type = Literal.__getitem__(agent_ids)
        operation_types.append(create_model(
            "_AgentOperationWithAdmittedCapability",
            __base__=_AgentOperationDraft,
            agent_id=(agent_id_type, ...),
        ))
    if "synthesis" in subgoal.capability_contract.allowed_execution_kinds:
        operation_types.append(_SynthesisOperationDraft)
    if "user_input" in subgoal.capability_contract.allowed_execution_kinds:
        operation_types.append(_UserInputOperationDraft)
    if not operation_types:
        return _ExecutionDraft
    operation_type: Any = operation_types[0]
    if len(operation_types) > 1:
        for candidate in operation_types[1:]:
            operation_type = operation_type | candidate
        operation_type = Annotated[
            operation_type,
            Field(discriminator="kind"),
        ]
    return create_model(
        "_ExecutionWithAdmittedCapability",
        __base__=_ExecutionDraft,
        operation=(operation_type, ...),
    )


class _ObservationDraft(_Model):
    statement: str
    evidence_refs: tuple[str, ...]
    contradicted_assumption_ids: tuple[str, ...] = ()
    affected_logical_subgoal_ids: tuple[str, ...] = ()


class _VerificationDraft(_Model):
    satisfied: bool
    evidence_refs: tuple[str, ...] = ()
    feedback: str = ""
    observations: tuple[_ObservationDraft, ...] = ()

    @model_validator(mode="after")
    def _require_repair_feedback_when_unsatisfied(self) -> "_VerificationDraft":
        if not self.satisfied and not self.feedback.strip():
            raise ValueError(
                "unsatisfied verification must provide actionable repair feedback"
            )
        return self


class _GeneratedContentDraft(_Model):
    content: str
    evidence_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class _FinalVerificationDraft(_Model):
    passed: bool
    feedback: str = ""


def _inventory_payload(inventory: RuntimeCapabilityInventory) -> dict[str, Any]:
    return {
        "local_capability_classes": [
            {
                "class_ref": f"tool:{item.tool_name}",
                "description": item.description,
                "identity_operation": item.tool_name,
                "semantic_domains": item.semantic_domains,
                "resource_types": item.resource_types,
                "operations": tuple(dict.fromkeys(
                    (*item.operations, item.tool_name)
                )),
                "allowed_execution_kinds": ("tool",),
            }
            for item in inventory.local_tools
            if (
                item.configuration_state == "enabled"
                and not item.authorization_scope.startswith("interaction:")
            )
        ],
        "mcp_capability_classes": [
            {
                "class_ref": (
                    f"mcp:{item.server_id}:{item.remote_tool_name}"
                ),
                "description": item.description,
                "identity_operation": item.local_tool_name,
                "semantic_domains": item.semantic_domains,
                "resource_types": item.resource_types,
                "operations": tuple(dict.fromkeys(
                    (*item.operations, item.local_tool_name)
                )),
                "allowed_execution_kinds": ("tool",),
            }
            for item in inventory.mcp_connectors
            if (
                item.configuration_state == "enabled"
                and item.discovery_state == "discovered"
            )
        ],
        "agent_capability_classes": [
            {
                "class_ref": f"agent:{item.agent_id}",
                "description": item.description,
                "identity_operation": item.agent_id,
                "semantic_domains": item.semantic_domains,
                "resource_types": item.resource_types,
                "operations": tuple(dict.fromkeys(
                    (*item.operations, item.agent_id)
                )),
                "allowed_execution_kinds": ("agent",),
            }
            for item in inventory.a2a_agents
            if (
                item.implementation_present
                and item.configuration_state == "enabled"
                and item.discovery_state == "registered_profile"
            )
        ],
        "application_capability_classes": [
            {
                "class_ref": "application:synthesis",
                "identity_operation": "synthesize",
                "semantic_domains": ("synthesis",),
                "resource_types": ("",),
                "operations": ("synthesize",),
                "allowed_execution_kinds": ("synthesis",),
            },
            {
                "class_ref": "application:user_input",
                "identity_operation": "request_user_input",
                "semantic_domains": ("user_input",),
                "resource_types": ("",),
                "operations": ("request_user_input",),
                "allowed_execution_kinds": ("user_input",),
            },
        ],
    }


def _compact_input_schema(value: Any) -> Any:
    """Keep executable schema constraints while dropping presentation-only bulk."""
    if isinstance(value, list):
        return [_compact_input_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    retained: dict[str, Any] = {}
    for key in (
        "type",
        "const",
        "enum",
        "required",
        "additionalProperties",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "pattern",
    ):
        if key in value:
            retained[key] = value[key]
    description = value.get("description")
    if isinstance(description, str) and description:
        retained["description"] = description[:240]
    for key in ("properties", "$defs", "definitions"):
        nested = value.get(key)
        if isinstance(nested, dict):
            retained[key] = {
                name: _compact_input_schema(schema)
                for name, schema in nested.items()
            }
    if "items" in value:
        retained["items"] = _compact_input_schema(value["items"])
    for key in ("anyOf", "oneOf", "allOf"):
        nested = value.get(key)
        if isinstance(nested, list):
            retained[key] = [_compact_input_schema(item) for item in nested]
    return retained


def _execution_inventory_payload(
    inventory: RuntimeCapabilityInventory,
    subgoal: SubGoalDefinitionVersion,
) -> dict[str, Any]:
    """Materialize only capabilities the accepted SubGoal can actually execute."""
    payload = matching_execution_inventory(
        inventory,
        subgoal.capability_contract,
    ).model_dump(mode="json")
    for item in payload["local_tools"]:
        item["input_schema"] = _compact_input_schema(item["input_schema"])
    return payload


def _usage(response, category) -> ProjectUsage:
    return ProjectUsage(
        category=category,
        reservation_id=f"model-port:{uuid4().hex[:16]}",
        tokens=max(0, int(response.total_tokens or 0)),
        estimated=response.total_tokens is None,
    )


def _evidence_material_payload(
    evidence_material: tuple[EvidenceMaterial, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "project_evidence_id": item.reference.evidence_id,
            "source": item.reference.source,
            "artifact_ref": (
                item.reference.artifact_ref.model_dump(mode="json")
                if item.reference.artifact_ref is not None
                else None
            ),
            "content_digest": item.reference.content_digest,
            "content": item.content,
        }
        for item in evidence_material
    ]


_ISO_DATE_WINDOW_PATTERN = re.compile(
    r"\b(?P<start>\d{4}-\d{2}-\d{2})\b"
    r"\s*(?:至|到|through|to|–|—)\s*"
    r"\b(?P<end>\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)
_ISO_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_URL_PATTERN = re.compile(r"https?://[^\s\]\)\"'<>]+")


def _observed_github_repository_paths(
    locators: tuple[str, ...],
) -> tuple[str, ...]:
    repositories: list[str] = []
    for locator in locators:
        parsed = urlparse(locator)
        if (parsed.hostname or "").lower() not in {"github.com", "www.github.com"}:
            continue
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            continue
        repositories.append(
            f"github.com/{parts[0]}/{parts[1].removesuffix('.git')}"
        )
    return tuple(dict.fromkeys(repositories))


def _observed_url_candidates(
    locators: tuple[str, ...],
) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "candidate_id": f"url_candidate_{index:02d}",
            "url": locator,
        }
        for index, locator in enumerate(locators, start=1)
    )


def _planning_evidence_payload(
    evidence_material: tuple[EvidenceMaterial, ...],
) -> list[dict[str, Any]]:
    payload = []
    for item in evidence_material:
        base = {
            "project_evidence_id": item.reference.evidence_id,
            "source": item.reference.source,
            "content_digest": item.reference.content_digest,
        }
        try:
            parsed = json.loads(item.content)
        except json.JSONDecodeError:
            parsed = None
        search_results = None
        if (
            isinstance(parsed, dict)
            and item.reference.source == "tool:web_search"
        ):
            data = parsed.get("data")
            if isinstance(data, dict) and isinstance(data.get("results"), list):
                search_results = data["results"]
        if isinstance(search_results, list):
            base["web_search_candidates"] = [
                {
                    "title": result.get("title"),
                    "url": result.get("url"),
                    "host": (
                        result.get("host")
                        or urlparse(str(result.get("url") or "")).hostname
                    ),
                    "provider_published_at": (
                        result.get("provider_published_at")
                        or result.get("published_at")
                    ),
                    "explicit_dates_in_title_or_snippet": (
                        result.get("explicit_dates_in_title_or_snippet")
                        or list(dict.fromkeys(_ISO_DATE_PATTERN.findall(
                            f"{result.get('title') or ''} "
                            f"{result.get('snippet') or ''}"
                        )))
                    ),
                    "bounded_snippet": str(result.get("snippet") or "")[:600],
                }
                for result in search_results
                if isinstance(result, dict)
            ]
        else:
            base["bounded_content_excerpt"] = item.content[:1200]
            base["linked_urls"] = list(dict.fromkeys(
                _URL_PATTERN.findall(item.content)
            ))[:40]
            base["explicit_iso_dates"] = list(dict.fromkeys(
                _ISO_DATE_PATTERN.findall(item.content)
            ))
        payload.append(base)
    return payload


def _repair_candidate_context(
    project: InvestigationProject,
    repair_gaps: tuple,
    evidence_material: tuple[EvidenceMaterial, ...],
) -> list[dict[str, Any]]:
    active_by_key = {
        (item.logical_subgoal_id, item.subgoal_version): item
        for item in project.active_plan_subgoals
    }
    context: list[dict[str, Any]] = []
    for gap in repair_gaps:
        gap_key = (gap.logical_subgoal_id, gap.subgoal_version)
        gap_subgoal = active_by_key.get(gap_key)
        scoped_keys = {gap_key}
        if gap_subgoal is not None:
            scoped_keys.update(
                execution_evidence_subgoal_keys(project, gap_subgoal)
            )
        scoped_execution_ids = {
            execution_ref.execution_id
            for key, execution_ref in project.execution_refs.items()
            if key in scoped_keys
        }
        scoped_material = tuple(
            item
            for item in evidence_material
            if item.reference.execution_ref.execution_id
            in scoped_execution_ids
        )
        context.append({
            "frozen_gap_ref": {
                "logical_subgoal_id": gap.logical_subgoal_id,
                "subgoal_version": gap.subgoal_version,
            },
            "required_repair_logical_subgoal_id": (
                repair_subgoal_logical_id(gap.logical_subgoal_id)
            ),
            "candidate_evidence": _planning_evidence_payload(
                scoped_material
            ),
        })
    return context


def _deterministic_iso_date_facts(
    goal: str,
    evidence_material: tuple[EvidenceMaterial, ...],
) -> dict[str, Any] | None:
    match = _ISO_DATE_WINDOW_PATTERN.search(goal)
    if match is None:
        return None
    try:
        start = date.fromisoformat(match.group("start"))
        end = date.fromisoformat(match.group("end"))
    except ValueError:
        return None
    if start > end:
        return None
    classifications = []
    for item in evidence_material:
        occurrences = tuple(dict.fromkeys(
            _ISO_DATE_PATTERN.findall(item.content)
        ))
        within_window = []
        outside_window = []
        invalid = []
        for value in occurrences:
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                invalid.append(value)
                continue
            (
                within_window
                if start <= parsed <= end
                else outside_window
            ).append(value)
        classifications.append({
            "project_evidence_id": item.reference.evidence_id,
            "within_inclusive_window": within_window,
            "outside_inclusive_window": outside_window,
            "invalid_iso_dates": invalid,
        })
    return {
        "inclusive_start": start.isoformat(),
        "inclusive_end": end.isoformat(),
        "classification_scope": (
            "Mechanical ISO date occurrences only; the Verifier still decides "
            "whether a date is an authoritative release date."
        ),
        "evidence": classifications,
    }


def _generated_content_output_type(
    evidence_material: tuple[EvidenceMaterial, ...],
) -> type[BaseModel]:
    allowed_ids = tuple(dict.fromkeys(
        item.reference.evidence_id
        for item in evidence_material
        if item.reference.source != "synthesis"
    ))
    if not allowed_ids:
        return _GeneratedContentDraft
    evidence_id_type = Literal.__getitem__(allowed_ids)
    return create_model(
        "_GeneratedContentWithAdmittedEvidence",
        __base__=_GeneratedContentDraft,
        evidence_refs=(
            tuple[evidence_id_type, ...],
            Field(min_length=1),
        ),
    )


def _final_generated_content_output_type(
    evidence_material: tuple[EvidenceMaterial, ...],
) -> type[BaseModel]:
    return create_model(
        "_FinalReportWithRequiredLimitations",
        __base__=_generated_content_output_type(evidence_material),
        content=(str, Field(min_length=1)),
        limitations=(tuple[str, ...], Field(min_length=1)),
    )


def _planner_capability_contract_output_type(
    inventory: RuntimeCapabilityInventory,
):
    execution_shapes: set[
        tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]
    ] = set()
    for item in inventory.local_tools:
        if (
            item.configuration_state == "enabled"
            and not item.authorization_scope.startswith("interaction:")
        ):
            execution_shapes.add((
                "tool",
                item.semantic_domains or ("",),
                item.resource_types or ("",),
                tuple(dict.fromkeys((*item.operations, item.tool_name))),
            ))
    for item in inventory.mcp_connectors:
        if (
            item.configuration_state == "enabled"
            and item.discovery_state == "discovered"
        ):
            execution_shapes.add((
                "tool",
                item.semantic_domains or ("",),
                item.resource_types or ("",),
                tuple(dict.fromkeys((*item.operations, item.local_tool_name))),
            ))
    for item in inventory.a2a_agents:
        if (
            item.implementation_present
            and item.configuration_state == "enabled"
            and item.discovery_state == "registered_profile"
        ):
            execution_shapes.add((
                "agent",
                item.semantic_domains or ("",),
                item.resource_types or ("",),
                tuple(dict.fromkeys((*item.operations, item.agent_id))),
            ))

    contract_types: list[type[BaseModel]] = []
    for index, (
        execution_kind,
        semantic_domains,
        resource_types,
        operations,
    ) in enumerate(sorted(execution_shapes)):
        contract_types.append(create_model(
            f"_PlannerExecutableCapabilityContract{index}",
            __base__=CapabilityContract,
            operation=(Literal.__getitem__(operations), ...),
            semantic_domain=(Literal.__getitem__(semantic_domains), ...),
            resource_type=(Literal.__getitem__(resource_types), ...),
            allowed_execution_kinds=(
                tuple[Literal.__getitem__((execution_kind,)), ...],
                Field(min_length=1, max_length=1),
            ),
        ))

    contract_types.extend((
        create_model(
            "_PlannerSynthesisCapabilityContract",
            __base__=CapabilityContract,
            operation=(Literal["synthesize"], "synthesize"),
            semantic_domain=(Literal["synthesis"], "synthesis"),
            allowed_execution_kinds=(
                tuple[Literal["synthesis"], ...],
                Field(default=("synthesis",), min_length=1, max_length=1),
            ),
        ),
        create_model(
            "_PlannerUserInputCapabilityContract",
            __base__=CapabilityContract,
            operation=(Literal["request_user_input"], "request_user_input"),
            semantic_domain=(Literal["user_input"], "user_input"),
            allowed_execution_kinds=(
                tuple[Literal["user_input"], ...],
                Field(default=("user_input",), min_length=1, max_length=1),
            ),
        ),
    ))
    contract_union = contract_types[0]
    for candidate in contract_types[1:]:
        contract_union = contract_union | candidate
    return contract_union


def _plan_output_type(inventory: RuntimeCapabilityInventory):
    capability_type = _planner_capability_contract_output_type(inventory)
    subgoal_type = create_model(
        "_AdmittedPlanSubGoalDraft",
        __base__=_SubGoalDraft,
        capability_contract=(capability_type, ...),
    )
    return create_model(
        "_PlanWithAdmittedCapabilityDomains",
        __base__=_PlanDraft,
        subgoals=(tuple[subgoal_type, ...], ...),
    )


def _revision_output_type(
    inventory: RuntimeCapabilityInventory,
    *,
    repair_gap_ids: tuple[str, ...],
):
    capability_type = _planner_capability_contract_output_type(inventory)
    revisable_type = create_model(
        "_AdmittedRevisableSubGoalDraft",
        __base__=_SubGoalDraft,
        capability_contract=(capability_type, ...),
    )
    if not repair_gap_ids:
        return create_model(
            "_PlanRevisionWithAdmittedCapabilityDomains",
            __base__=_PlanRevisionDraft,
            revisable_subgoals=(tuple[revisable_type, ...], ()),
        )
    repair_types = []
    for index, repair_gap_id in enumerate(repair_gap_ids):
        repair_id_type = Literal.__getitem__((repair_gap_id,))
        logical_id_type = Literal.__getitem__((
            repair_subgoal_logical_id(repair_gap_id),
        ))
        repair_types.append(create_model(
            (
                "_AdmittedIndependentRepairSubGoalDraft"
                if len(repair_gap_ids) == 1
                else f"_AdmittedIndependentRepairSubGoalDraft{index}"
            ),
            __base__=_IndependentRepairSubGoalDraft,
            logical_subgoal_id=(logical_id_type, ...),
            capability_contract=(capability_type, ...),
            repairs_frozen_logical_subgoal_ids=(
                tuple[repair_id_type, ...],
                Field(min_length=1, max_length=1),
            ),
        ))
    repair_type: Any = repair_types[0]
    for candidate in repair_types[1:]:
        repair_type = repair_type | candidate
    if len(repair_types) > 1:
        repair_type = Annotated[
            repair_type,
            Field(discriminator="logical_subgoal_id"),
        ]
    return create_model(
        "_RepairPlanRevisionWithAdmittedCapabilityDomains",
        __base__=_RepairPlanRevisionDraft,
        revisable_subgoals=(tuple[revisable_type, ...], ()),
        independent_repair_subgoals=(
            tuple[repair_type, ...],
            Field(min_length=1),
        ),
    )


def _request(
    *,
    operation: str,
    output_type,
    system: str,
    payload: dict[str, Any],
    max_tokens: int,
) -> StructuredModelRequest:
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        },
    ]
    return StructuredModelRequest(
        operation=operation,
        version="v1",
        messages=messages,
        output_type=output_type,
        context_projection_ref=sealed_context_projection_ref(
            purpose=operation,
            messages=messages,
        ),
        temperature=0,
        max_tokens=max_tokens,
    )


class StructuredInvestigationPlanner:
    def __init__(self, model: StructuredModelClient) -> None:
        self._model = model

    def propose_initial(
        self,
        definition: InvestigationProjectDefinition,
        *,
        based_on_event_sequence: int,
        repair_request: ReplanRequest | None,
        capabilities: RuntimeCapabilityInventory,
        capability_revision: str,
    ) -> ModelDecision[PlanProposal]:
        response = self._model.generate(_request(
            operation="investigation_project_plan",
            output_type=_plan_output_type(capabilities),
            system=(
                "You are the semantic Planner. Preserve every active user requirement. "
                "Return dynamic subgoals, dependencies, required outputs and capability "
                "contracts. Every active user requirement and every derived requirement "
                "must bind its outcome-producing SubGoals in "
                "mapped_logical_subgoal_ids. requirement_mappings is only for active "
                "user requirements. Choose a supplied capability class, never a Provider "
                "binding, authorization, state, or completion. Copy its exact "
                "identity_operation when multiple classes share broad dimensions. When "
                "acceptance "
                "requires independently verified facts from multiple named sources, "
                "protocols, or subjects, create separate evidence-acquisition subgoals so "
                "one broad retrieval is not the sole evidence for every required item. "
                "Every SubGoal is automatically checked by the Project semantic Verifier; "
                "semantic verification or validation is never a Plan SubGoal of any "
                "execution kind. Do not create a verification-domain SubGoal to check "
                "evidence, exclusions, another SubGoal, or completion. A user-visible "
                "source-authority, date-window, exclusion, sufficiency, or compliance "
                "check is not acquisition work: encode those constraints in the evidence "
                "SubGoal required_output and let the automatic Verifier judge them. Before "
                "returning, remove every SubGoal whose actual purpose is to verify, "
                "validate, check, or confirm whether another SubGoal or source satisfies "
                "a requirement, regardless of the capability class assigned to it. A "
                "user-visible "
                "audit artifact is analysis/report synthesis, not semantic verification. "
                "Use execution kind synthesis with semantic_domain=synthesis for report "
                "composition, and semantic_domain=user_input for user input. Other "
                "semantic_domain values must be copied exactly from a supplied capability "
                "class. Capability contract dimensions must match one supplied capability "
                "class unless the kind is synthesis or user_input. When "
                "admission_repair_request is present, return a corrected complete initial "
                "plan that addresses its typed DecisionFeedback."
            ),
            payload={
                "project_id": definition.project_id,
                "goal": definition.goal,
                "user_requirements": definition.user_requirements.model_dump(mode="json"),
                "admission_repair_request": (
                    repair_request.model_dump(mode="json")
                    if repair_request is not None
                    else None
                ),
                "capabilities": _inventory_payload(capabilities),
                "capability_revision": capability_revision,
            },
            max_tokens=3000,
        ))
        proposal = self._materialize(
            response.value,
            project_id=definition.project_id,
            based_on_event_sequence=based_on_event_sequence,
            capability_revision=capability_revision,
            revision_reason="initial",
        )
        return ModelDecision(proposal, _usage(response, "planning"))

    def propose_revision(
        self,
        project: InvestigationProject,
        request: ReplanRequest,
        *,
        evidence_material: tuple[EvidenceMaterial, ...],
        capabilities: RuntimeCapabilityInventory,
        capability_revision: str,
    ) -> ModelDecision[PlanProposal]:
        accepted_plan = project.accepted_plan
        if accepted_plan is None:
            raise ValueError("plan revision requires an accepted plan")
        frozen_keys = frozen_subgoal_keys(project)
        frozen_subgoals = tuple(
            item
            for item in accepted_plan.proposal.subgoals
            if (item.logical_subgoal_id, item.subgoal_version) in frozen_keys
        )
        revisable_subgoals = tuple(
            item
            for item in accepted_plan.proposal.subgoals
            if (item.logical_subgoal_id, item.subgoal_version) not in frozen_keys
        )
        repair_gaps = tuple(
            item
            for key, item in project.waiting_reasons.items()
            if item.reason == "verification_repair" and key in frozen_keys
        )
        revision_output_type = _revision_output_type(
            capabilities,
            repair_gap_ids=tuple(
                item.logical_subgoal_id for item in repair_gaps
            ),
        )
        repair_instruction = (
            " This revision has frozen verification gaps. Emit at least one new "
            "independent_repair_subgoals item for those gaps; its depends_on must be "
            "empty so it is runnable without frozen work, and list the exact frozen "
            "logical ids it repairs in repairs_frozen_logical_subgoal_ids. Application "
            "will deterministically replace their requirement mappings. When the gap "
            "is evidentiary and no capability change is reported, preserve the supplied "
            "read-only capability_contract_template instead of inventing a broader "
            "composite operation. A plausible authoritative URL in candidate evidence "
            "with an insufficient snippet is an explicit capability change: select the "
            "supplied class whose description reads or captures a URL, copy its "
            "identity_operation, and do not repeat the search class."
            if repair_gaps
            else ""
        )
        response = self._model.generate(_request(
            operation="investigation_project_replan",
            output_type=revision_output_type,
            system=(
                "Return only the semantically revisable portion of the Project plan in "
                "revisable_subgoals. Every id in forbidden_logical_subgoal_ids is a frozen "
                "canonical execution fact: never emit any of those ids in "
                "revisable_subgoals. For a verification-repair revision this output is a "
                "patch: Application retains omitted prior non-frozen SubGoals because "
                "their canonical requirement mappings are not model-writable here. Emit "
                "an existing non-frozen id only when changing its definition. Application "
                "deterministically owns version and supersede derivation. Every independent "
                "repair logical id must be new and absent "
                "from forbidden_logical_subgoal_ids; never reuse a prior repair id. Never "
                "modify user requirements, completed "
                "outcomes, accepted executions, commands, or receipts. When a frozen "
                "SubGoal has a verification gap, required coverage must not map to it and "
                "new work must not depend on its completion. Add independently runnable "
                "corroboration or repair work with new logical ids and map required "
                "coverage only to verifiable outcomes. Every SubGoal is automatically "
                "checked by the Project semantic Verifier; semantic verification or "
                "validation is never a Plan SubGoal of any execution kind. Do not create "
                "a verification-domain SubGoal to check evidence, exclusions, another "
                "SubGoal, or completion. Use execution kind synthesis for report "
                "composition with semantic_domain=synthesis, and use "
                "semantic_domain=user_input for user input. Other semantic_domain values "
                "must be copied exactly from a supplied capability class. Capability "
                "contract dimensions must match one supplied capability class unless the "
                "kind is synthesis or user_input. Copy its exact identity_operation when "
                "multiple classes share broad dimensions. "
                "Admitted evidence from an unsatisfied search is candidate context, not "
                "verified coverage. When it exposes a plausible authoritative URL but "
                "snippets are insufficient, create independent page-reading work for "
                "that URL instead of repeating the same broad search. A candidate is "
                "plausible only when its URL, title, provider date, explicit dates, and "
                "snippet do not contradict any required date window, source class, or "
                "exclusion. If no observed candidate satisfies all those constraints, "
                "create a new focused search repair rather than page-reading work. "
                "Source-authority, date-window, exclusion, sufficiency, or compliance "
                "checking is owned by the automatic Verifier and must never become a "
                "separate Plan SubGoal under another capability class. Before returning, "
                "remove every SubGoal whose actual purpose is to verify, validate, check, "
                "or confirm another SubGoal or source. Waiting reasons "
                "whose reason is not verification_repair are immutable environment or "
                "execution facts with their own recovery authority; never include their "
                "logical ids in repair declarations or create replacement work for them. "
                "prior_unverified_tool_operations are immutable executions already judged "
                "insufficient for verified coverage; never request repair work that would "
                "repeat one exactly. For every frozen gap, copy its "
                "required_repair_logical_subgoal_id exactly; repair identities are "
                "deterministic and model-generated alternatives are invalid. Use only the "
                "candidate evidence grouped under that same frozen gap; never use one "
                "gap's candidates to choose another gap's source."
                + repair_instruction
            ),
            payload={
                "project_definition": project.definition.model_dump(mode="json"),
                "user_requirements": project.user_requirements.model_dump(mode="json"),
                "current_assumptions": [
                    item.model_dump(mode="json")
                    for item in accepted_plan.proposal.assumptions
                ],
                "current_derived_requirements": [
                    item.model_dump(mode="json")
                    for item in accepted_plan.proposal.derived_requirements
                ],
                "frozen_subgoal_refs_read_only": [
                    {
                        "logical_subgoal_id": item.logical_subgoal_id,
                        "subgoal_version": item.subgoal_version,
                        "definition_digest": item.definition_digest,
                    }
                    for item in frozen_subgoals
                ],
                "forbidden_logical_subgoal_ids": [
                    item.logical_subgoal_id for item in frozen_subgoals
                ],
                "revisable_subgoals": [
                    item.model_dump(mode="json") for item in revisable_subgoals
                ],
                "current_user_requirement_mappings": [
                    item.model_dump(mode="json")
                    for item in accepted_plan.proposal.requirement_mappings
                    if item.requirement_id in {
                        requirement.requirement_id
                        for requirement in project.user_requirements.requirements
                    }
                ],
                "outcomes": [
                    item.model_dump(mode="json")
                    for item in project.outcomes.values()
                ],
                "admitted_evidence_candidate_context": (
                    []
                    if repair_gaps
                    else _planning_evidence_payload(evidence_material)
                ),
                "repair_candidate_context": _repair_candidate_context(
                    project,
                    repair_gaps,
                    evidence_material,
                ),
                "waiting_reasons_read_only": [
                    item.model_dump(mode="json")
                    for item in project.waiting_reasons.values()
                ],
                "prior_unverified_tool_operations": [
                    item.model_dump(mode="json")
                    for item in unverified_tool_execution_operations(project)
                ],
                "required_independent_repairs": [
                    {
                        "frozen_logical_subgoal_id": item.logical_subgoal_id,
                        "frozen_subgoal_version": item.subgoal_version,
                        "required_repair_logical_subgoal_id": (
                            repair_subgoal_logical_id(
                                item.logical_subgoal_id
                            )
                        ),
                        "verification_gap": item.detail,
                        "capability_contract_template": next(
                            subgoal.capability_contract.model_dump(mode="json")
                            for subgoal in frozen_subgoals
                            if (
                                subgoal.logical_subgoal_id
                                == item.logical_subgoal_id
                                and subgoal.subgoal_version
                                == item.subgoal_version
                            )
                        ),
                    }
                    for item in repair_gaps
                ],
                "replan_request": request.model_dump(mode="json"),
                "capabilities": _inventory_payload(capabilities),
                "capability_revision": capability_revision,
            },
            max_tokens=3500,
        ))
        proposal = self._materialize_revision(
            response.value,
            project_id=project.definition.project_id,
            based_on_event_sequence=project.event_sequence,
            capability_revision=capability_revision,
            revision_reason=request.request_id,
            frozen_subgoals=frozen_subgoals,
            previous_subgoals=accepted_plan.proposal.subgoals,
            previous_requirement_mappings=(
                accepted_plan.proposal.requirement_mappings
            ),
            previous_derived_requirement_ids=tuple(
                item.requirement_id
                for item in accepted_plan.proposal.derived_requirements
            ),
            frozen_gap_ids=tuple(
                item.logical_subgoal_id for item in repair_gaps
            ),
        )
        return ModelDecision(proposal, _usage(response, "planning"))

    @staticmethod
    def _materialize(
        draft: _PlanDraft,
        *,
        project_id: str,
        based_on_event_sequence: int,
        capability_revision: str,
        revision_reason: str,
    ) -> PlanProposal:
        subgoals = []
        for item in draft.subgoals:
            temporary = SubGoalDefinitionVersion(
                **item.model_dump(),
                subgoal_version=1,
                supersedes_version=None,
                definition_digest="0" * 64,
            )
            subgoals.append(temporary.model_copy(
                update={"definition_digest": subgoal_definition_digest(temporary)}
            ))
        return PlanProposal(
            project_id=project_id,
            based_on_event_sequence=based_on_event_sequence,
            capability_snapshot_revision=capability_revision,
            revision_reason=revision_reason,
            assumptions=draft.assumptions,
            derived_requirements=tuple(
                DerivedRequirement(
                    **item.model_dump(
                        exclude={"mapped_logical_subgoal_ids"}
                    )
                )
                for item in draft.derived_requirements
            ),
            subgoals=tuple(subgoals),
            requirement_mappings=(
                *draft.requirement_mappings,
                *(
                    RequirementMapping(
                        requirement_id=item.requirement_id,
                        logical_subgoal_ids=item.mapped_logical_subgoal_ids,
                    )
                    for item in draft.derived_requirements
                ),
            ),
        )

    @staticmethod
    def _materialize_revision(
        draft: _PlanRevisionDraft | _RepairPlanRevisionDraft,
        *,
        project_id: str,
        based_on_event_sequence: int,
        capability_revision: str,
        revision_reason: str,
        frozen_subgoals: tuple[SubGoalDefinitionVersion, ...],
        previous_subgoals: tuple[SubGoalDefinitionVersion, ...],
        previous_requirement_mappings: tuple[RequirementMapping, ...],
        previous_derived_requirement_ids: tuple[str, ...],
        frozen_gap_ids: tuple[str, ...],
    ) -> PlanProposal:
        revisable_subgoals = []
        previous_by_id = {
            item.logical_subgoal_id: item for item in previous_subgoals
        }
        explicit_subgoals = (
            draft.revisable_subgoals
            + (
                draft.independent_repair_subgoals
                if isinstance(draft, _RepairPlanRevisionDraft)
                else ()
            )
        )
        if isinstance(draft, _RepairPlanRevisionDraft):
            frozen_ids = {
                item.logical_subgoal_id for item in frozen_subgoals
            }
            explicit_ids = {
                item.logical_subgoal_id for item in explicit_subgoals
            }
            revisable_subgoals.extend(
                item
                for item in previous_subgoals
                if (
                    item.logical_subgoal_id not in frozen_ids
                    and item.logical_subgoal_id not in explicit_ids
                )
            )
        for item in explicit_subgoals:
            previous = previous_by_id.get(item.logical_subgoal_id)
            repair_refs = (
                tuple(
                    SubGoalVersionRef(
                        logical_subgoal_id=logical_subgoal_id,
                        subgoal_version=next(
                            frozen.subgoal_version
                            for frozen in frozen_subgoals
                            if frozen.logical_subgoal_id == logical_subgoal_id
                        ),
                    )
                    for logical_subgoal_id
                    in item.repairs_frozen_logical_subgoal_ids
                )
                if isinstance(item, _IndependentRepairSubGoalDraft)
                else ()
            )
            temporary = SubGoalDefinitionVersion(
                **item.model_dump(
                    exclude={"repairs_frozen_logical_subgoal_ids"}
                ),
                subgoal_version=(
                    previous.subgoal_version if previous is not None else 1
                ),
                supersedes_version=(
                    previous.supersedes_version if previous is not None else None
                ),
                definition_digest="0" * 64,
                repairs_frozen_subgoals=repair_refs,
            )
            digest = subgoal_definition_digest(temporary)
            if previous is not None and digest == previous.definition_digest:
                revisable_subgoals.append(previous)
                continue
            if previous is not None:
                temporary = temporary.model_copy(update={
                    "subgoal_version": previous.subgoal_version + 1,
                    "supersedes_version": previous.subgoal_version,
                })
                digest = subgoal_definition_digest(temporary)
            revisable_subgoals.append(temporary.model_copy(
                update={"definition_digest": digest}
            ))
        requirement_mappings = (
            StructuredInvestigationPlanner._repair_requirement_mappings(
                draft,
                previous_requirement_mappings=previous_requirement_mappings,
                frozen_gap_ids=frozen_gap_ids,
            )
            if isinstance(draft, _RepairPlanRevisionDraft)
            else draft.requirement_mappings
        )
        requirement_mappings = (
            StructuredInvestigationPlanner._replace_derived_requirement_mappings(
                requirement_mappings,
                draft.derived_requirements,
                previous_derived_requirement_ids=(
                    previous_derived_requirement_ids
                ),
            )
        )
        return PlanProposal(
            project_id=project_id,
            based_on_event_sequence=based_on_event_sequence,
            capability_snapshot_revision=capability_revision,
            revision_reason=revision_reason,
            assumptions=draft.assumptions,
            derived_requirements=tuple(
                DerivedRequirement(
                    **item.model_dump(
                        exclude={"mapped_logical_subgoal_ids"}
                    )
                )
                for item in draft.derived_requirements
            ),
            subgoals=(*frozen_subgoals, *revisable_subgoals),
            requirement_mappings=requirement_mappings,
        )

    @staticmethod
    def _replace_derived_requirement_mappings(
        base_mappings: tuple[RequirementMapping, ...],
        derived_requirements: tuple[_DerivedRequirementDraft, ...],
        *,
        previous_derived_requirement_ids: tuple[str, ...],
    ) -> tuple[RequirementMapping, ...]:
        derived_ids = {
            item.requirement_id for item in derived_requirements
        }
        replaceable_ids = (
            set(previous_derived_requirement_ids) | derived_ids
        )
        return (
            *(
                mapping
                for mapping in base_mappings
                if mapping.requirement_id not in replaceable_ids
            ),
            *(
                RequirementMapping(
                    requirement_id=item.requirement_id,
                    logical_subgoal_ids=item.mapped_logical_subgoal_ids,
                )
                for item in derived_requirements
            ),
        )

    @staticmethod
    def _repair_requirement_mappings(
        draft: _RepairPlanRevisionDraft,
        *,
        previous_requirement_mappings: tuple[RequirementMapping, ...],
        frozen_gap_ids: tuple[str, ...],
    ) -> tuple[RequirementMapping, ...]:
        gap_ids = set(frozen_gap_ids)
        replacements: dict[str, list[str]] = {
            gap_id: [] for gap_id in frozen_gap_ids
        }
        for repair in draft.independent_repair_subgoals:
            unknown = set(repair.repairs_frozen_logical_subgoal_ids) - gap_ids
            if unknown:
                raise ValueError(
                    f"repair references unknown frozen gaps: {sorted(unknown)}"
                )
            for gap_id in repair.repairs_frozen_logical_subgoal_ids:
                replacements[gap_id].append(repair.logical_subgoal_id)
        missing = sorted(
            gap_id for gap_id, ids in replacements.items() if not ids
        )
        if missing:
            raise ValueError(
                f"frozen verification gaps lack repair work: {missing}"
            )
        mappings = []
        for mapping in previous_requirement_mappings:
            logical_ids: list[str] = []
            for logical_id in mapping.logical_subgoal_ids:
                if logical_id in gap_ids:
                    logical_ids.extend(replacements[logical_id])
                else:
                    logical_ids.append(logical_id)
            mappings.append(RequirementMapping(
                requirement_id=mapping.requirement_id,
                logical_subgoal_ids=tuple(dict.fromkeys(logical_ids)),
            ))
        return tuple(mappings)


class StructuredExecutionProposer:
    def __init__(self, model: StructuredModelClient) -> None:
        self._model = model

    def propose(
        self,
        project: InvestigationProject,
        subgoal: SubGoalDefinitionVersion,
        *,
        evidence_material: tuple[EvidenceMaterial, ...],
        execution_scope: ExecutionScope,
        capabilities: RuntimeCapabilityInventory,
    ) -> ModelDecision[SubGoalExecutionProposal]:
        subgoal_key = (subgoal.logical_subgoal_id, subgoal.subgoal_version)
        decision_feedback = project.execution_proposal_feedback.get(
            subgoal_key,
            (),
        )
        evidence_scope_keys = execution_evidence_subgoal_keys(project, subgoal)
        prior_unverified_operations = unverified_tool_execution_operations(
            project,
            subgoal_keys=evidence_scope_keys,
        )
        attempted_capture_urls = {
            str(item.typed_arguments.get("url"))
            for item in prior_unverified_operations
            if (
                item.tool_name == "capture_url"
                and item.typed_arguments.get("url")
            )
        }
        observed_locators = tuple(
            locator
            for locator in observed_url_locators(project, evidence_material)
            if locator not in attempted_capture_urls
        )
        observed_url_candidates = _observed_url_candidates(
            observed_locators
        )
        response = self._model.generate(_request(
            operation="investigation_subgoal_execution_proposal",
            output_type=_execution_output_type(
                capabilities,
                subgoal,
                observed_url_locators=observed_locators,
                excluded_tool_operations=prior_unverified_operations,
            ),
            system=(
                "Select one concrete operation from the supplied effective capabilities. "
                "Return its complete typed payload. Do not invent capabilities, modify the "
                "accepted subgoal, grant authorization, or claim execution/completion. "
                "For web search, use one focused query for the current subgoal. Copy every "
                "explicit date window and named subject from the accepted SubGoal and "
                "Project goal into that query; omitting either makes the query invalid. "
                "Use domain or site operators when they are needed to satisfy an official "
                "source-class constraint. Preserve the user's required source class and "
                "exclusions in the query; never add an excluded host or source class back "
                "through an OR clause or alternative search branch. When narrowing a "
                "GitHub search, copy owner/repository identity from "
                "observed_github_repository_paths instead of recalling or guessing an "
                "older repository identity. For "
                "example, a request for formal publication evidence must search for the "
                "official specification, changelog, or release notes rather than a generic "
                "topic page or product blog. Request page scraping when the required "
                "output needs publication dates, provenance, or source details that "
                "snippets may omit. For capture_url, choose only a candidate_id present "
                "in observed_url_candidates; Application deterministically binds it to "
                "the canonical URL from prior execution facts, and inventing or "
                "rewriting a URL is forbidden. If the "
                "Project excludes product blogs, do not choose a candidate whose hostname "
                "or path identifies it as a blog. For official GitHub release evidence, "
                "prefer an observed /releases page or changelog over a repository root. "
                "Never "
                "repeat an exact operation listed in "
                "prior_unverified_tool_operations; its execution evidence already failed "
                "semantic verification, so choose different arguments or another admitted "
                "capability. Repair only the mutable fields named in "
                "prior_execution_proposal_feedback; keep the accepted Plan and SubGoal "
                "binding unchanged."
            ),
            payload={
                "project_goal": project.definition.goal,
                "subgoal": subgoal.model_dump(mode="json"),
                "admitted_evidence": _planning_evidence_payload(evidence_material),
                "observed_url_locators": observed_locators,
                "observed_url_candidates": observed_url_candidates,
                "observed_github_repository_paths": (
                    _observed_github_repository_paths(observed_locators)
                ),
                "deterministic_iso_date_facts": _deterministic_iso_date_facts(
                    project.definition.goal,
                    evidence_material,
                ),
                "prior_unverified_tool_operations": [
                    item.model_dump(mode="json")
                    for item in prior_unverified_operations
                ],
                "prior_execution_proposal_feedback": [
                    item.model_dump(mode="json")
                    for item in decision_feedback
                ],
                "capabilities": _execution_inventory_payload(capabilities, subgoal),
                "execution_scope": execution_scope.model_dump(mode="json"),
            },
            max_tokens=1600,
        ))
        operation = _operation_from_draft(
            response.value.operation,
            observed_url_candidates=observed_url_candidates,
        )
        proposal_id = new_proposal_id()
        binding = {
            "project_id": project.definition.project_id,
            "plan_version": project.accepted_plan.plan_version,
            "logical_subgoal_id": subgoal.logical_subgoal_id,
            "subgoal_version": subgoal.subgoal_version,
            "based_on_event_sequence": project.event_sequence,
            "proposal_id": proposal_id,
            "operation": operation.model_dump(mode="json"),
        }
        proposal = SubGoalExecutionProposal(
            **binding,
            proposal_digest=canonical_digest(binding),
        )
        return ModelDecision(proposal, _usage(response, "execution_proposal"))


class StructuredProjectVerifier:
    def __init__(self, model: StructuredModelClient) -> None:
        self._model = model

    def verify_subgoal(
        self,
        project: InvestigationProject,
        subgoal: SubGoalDefinitionVersion,
        evidence: tuple,
        *,
        evidence_material: tuple,
        execution_scope: ExecutionScope,
    ) -> ModelDecision[SubGoalVerificationAssessment]:
        response = self._model.generate(_request(
            operation="investigation_subgoal_verification",
            output_type=_VerificationDraft,
            system=(
                "Judge whether admitted evidence semantically satisfies this bounded "
                "accepted SubGoal objective and required output. The Project goal and "
                "active requirements provide applicable constraints, but this SubGoal "
                "must not be required to cover subjects or comparison work assigned to "
                "other mapped SubGoals; full requirement coverage belongs to the "
                "Completion Gate. Treat source exclusions and date windows as hard "
                "constraints. A non-relied excluded candidate appearing in a multi-result "
                "search does not by itself invalidate valid non-excluded evidence; never "
                "use the excluded candidate to satisfy the SubGoal. When the goal excludes "
                "product blogs, a vendor's own product or developer blog is still a "
                "product blog; official provenance does not override the explicit "
                "source-type exclusion. Do not support any observation with an excluded "
                "candidate. Return satisfied=true only when affirmative observations, "
                "directly supported by non-excluded admitted evidence, collectively "
                "establish the bounded objective and required output. Execution success, "
                "the presence of search candidates, or evaluating rejected candidates is "
                "not semantic satisfaction. If every observation says a candidate is "
                "excluded, undated, unofficial, or otherwise insufficient, return "
                "satisfied=false with actionable feedback describing the missing evidence. "
                "Date windows are "
                "inclusive. deterministic_iso_date_facts owns mechanical ISO date "
                "comparison when present; never contradict its within/outside "
                "classification, while still deciding semantically whether an occurrence "
                "is an authoritative release date. Do not discard an explicit official release "
                "date in source content merely because provider published_at metadata is "
                "null. Use only evidence ids supplied. Every returned evidence_refs entry "
                "must be one of the "
                "top-level project_evidence_id values; nested provider source hashes and "
                "URLs are locators, not Project evidence ids. Do not override execution "
                "facts or authorization."
            ),
            payload={
                "project_goal": project.definition.goal,
                "requirements": project.user_requirements.model_dump(mode="json"),
                "subgoal": subgoal.model_dump(mode="json"),
                "evidence": _evidence_material_payload(evidence_material),
                "deterministic_iso_date_facts": _deterministic_iso_date_facts(
                    project.definition.goal,
                    evidence_material,
                ),
                "execution_scope": execution_scope.model_dump(mode="json"),
            },
            max_tokens=1000,
        ))
        value = response.value
        assessment_payload = {
            "logical_subgoal_id": subgoal.logical_subgoal_id,
            "subgoal_version": subgoal.subgoal_version,
            "satisfied": value.satisfied,
            "evidence_refs": value.evidence_refs,
            "feedback": value.feedback,
            "observations": [
                {
                    **item.model_dump(mode="python"),
                    "observation_digest": canonical_digest(item.model_dump(mode="json")),
                }
                for item in value.observations
            ],
        }
        assessment = SubGoalVerificationAssessment(
            **assessment_payload,
            assessment_digest=canonical_digest(assessment_payload),
        )
        return ModelDecision(assessment, _usage(response, "semantic_verification"))

    def verify_final(
        self,
        project: InvestigationProject,
        generated: GeneratedContent,
        *,
        evidence_material: tuple[EvidenceMaterial, ...],
        execution_scope: ExecutionScope,
    ) -> ModelDecision[FinalVerificationResult]:
        response = self._model.generate(_request(
            operation="investigation_final_report_verification",
            output_type=_FinalVerificationDraft,
            system=(
                "Verify that the report covers every active required contract, maps claims "
                "to admitted evidence, respects every exclusion and date window in the "
                "Project goal, and states limitations. Return passed=false if the report "
                "cites or relies on an excluded source, contradicts an exclusion, contains "
                "an unsupported claim, or misses required coverage. Treat date windows as "
                "inclusive and compare ISO dates chronologically."
            ),
            payload={
                "goal": project.definition.goal,
                "requirements": project.user_requirements.model_dump(mode="json"),
                "coverage": project.requirement_coverage(),
                "report": generated.content,
                "limitations": generated.limitations,
                "evidence_refs": generated.evidence_refs,
                "evidence": _evidence_material_payload(evidence_material),
                "execution_scope": execution_scope.model_dump(mode="json"),
            },
            max_tokens=900,
        ))
        return ModelDecision(
            FinalVerificationResult(
                passed=response.value.passed,
                feedback=response.value.feedback,
            ),
            _usage(response, "semantic_verification"),
        )


class StructuredProjectSynthesis:
    def __init__(self, model: StructuredModelClient) -> None:
        self._model = model

    def synthesize_subgoal(
        self,
        project: InvestigationProject,
        proposal: SubGoalExecutionProposal,
        *,
        evidence_material: tuple[EvidenceMaterial, ...],
        execution_scope: ExecutionScope,
    ) -> ModelDecision[GeneratedContent]:
        response = self._model.generate(_request(
            operation="investigation_subgoal_synthesis",
            output_type=_generated_content_output_type(evidence_material),
            system=(
                "Synthesize the requested bounded output from admitted evidence only. "
                "Respect every source exclusion in the Project goal and requirements; "
                "never cite or rely on an excluded source. Return every supporting "
                "direct tool or agent evidence id and explicit limitations. A prior "
                "synthesis is derived output, not authoritative source evidence. Every "
                "evidence_refs entry must be one of the supplied top-level "
                "project_evidence_id values; never return nested provider source hashes "
                "or URLs as evidence ids."
            ),
            payload={
                "goal": project.definition.goal,
                "requirements": project.user_requirements.model_dump(mode="json"),
                "operation": proposal.operation.model_dump(mode="json"),
                "admitted_evidence": _evidence_material_payload(evidence_material),
                "execution_scope": execution_scope.model_dump(mode="json"),
            },
            max_tokens=2200,
        ))
        generated = _generated(response.value)
        return ModelDecision(generated, _usage(response, "synthesis"))

    def synthesize_final(
        self,
        project: InvestigationProject,
        plan,
        *,
        evidence_material: tuple[EvidenceMaterial, ...],
        execution_scope: ExecutionScope,
    ) -> ModelDecision[GeneratedContent]:
        response = self._model.generate(_request(
            operation="investigation_final_report_synthesis",
            output_type=_final_generated_content_output_type(
                evidence_material
            ),
            system=(
                "Create the final investigation report. Cover every active required "
                "contract, cite only admitted evidence ids, preserve uncertainty, and "
                "include limitations. Treat every source exclusion in the Project goal "
                "and requirements as a hard constraint: never cite, rely on, or describe "
                "an excluded source as accepted evidence. Cite direct tool or agent "
                "evidence ids; prior synthesis output is not authoritative source "
                "evidence. Every evidence_refs entry must be one of the supplied "
                "top-level project_evidence_id values; never return nested provider "
                "source hashes or URLs as evidence ids. Materialize every user-visible "
                "acceptance field inside the report content itself: for each compared "
                "item include its source URL and release date, and include an explicit "
                "limitations section. The structured evidence_refs and limitations "
                "fields are lineage metadata and do not substitute for readable report "
                "content. Do not claim completion."
            ),
            payload={
                "goal": project.definition.goal,
                "requirements": project.user_requirements.model_dump(mode="json"),
                "plan": plan.model_dump(mode="json"),
                "outcomes": [
                    item.model_dump(mode="json")
                    for item in project.outcomes.values()
                ],
                "admitted_evidence": _evidence_material_payload(evidence_material),
                "execution_scope": execution_scope.model_dump(mode="json"),
            },
            max_tokens=4000,
        ))
        generated = _generated(response.value)
        return ModelDecision(generated, _usage(response, "synthesis"))


class UnavailableInvestigationModelPorts(
    StructuredInvestigationPlanner,
    StructuredExecutionProposer,
    StructuredProjectVerifier,
    StructuredProjectSynthesis,
):
    def __init__(self) -> None:
        pass

    def __getattribute__(self, name: str):
        if name.startswith("propose") or name.startswith("verify") or name.startswith("synthesize"):
            raise RuntimeError("structured model capability is not configured")
        return super().__getattribute__(name)


def _operation_from_draft(
    draft,
    *,
    observed_url_candidates: tuple[dict[str, str], ...] = (),
):
    payload = draft.model_dump(mode="python")
    if draft.kind == "tool" and draft.tool_name == "capture_url":
        candidate_id = payload["typed_arguments"].get("candidate_id")
        if candidate_id is not None:
            candidate_urls = {
                item["candidate_id"]: item["url"]
                for item in observed_url_candidates
            }
            payload["typed_arguments"] = {
                "url": candidate_urls[candidate_id],
            }
    return {
        "tool": ToolExecutionOperation,
        "agent": AgentExecutionOperation,
        "synthesis": SynthesisOperation,
        "user_input": UserInputOperation,
    }[draft.kind](**payload)


def _generated(value: _GeneratedContentDraft) -> GeneratedContent:
    return GeneratedContent(
        content=value.content,
        content_digest=canonical_digest({"content": value.content}),
        evidence_refs=value.evidence_refs,
        limitations=value.limitations,
    )


__all__ = [
    "StructuredExecutionProposer",
    "StructuredInvestigationPlanner",
    "StructuredProjectSynthesis",
    "StructuredProjectVerifier",
    "UnavailableInvestigationModelPorts",
]
