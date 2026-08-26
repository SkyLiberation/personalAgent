from __future__ import annotations

import json

import pytest

import personal_agent.application.investigation_project.model_ports as investigation_model_ports
from personal_agent.application.investigation_project.admission import (
    ExecutionProposalAdmission,
    PlanAdmission,
    ProposalRejected,
    compiled_agent_bounded_sub_goal,
    observed_url_locators,
    subgoal_definition_digest,
    unverified_tool_execution_operations,
)
from personal_agent.application.investigation_project.budget import ProjectBudgetLedger
from personal_agent.application.investigation_project.model_ports import (
    StructuredExecutionProposer,
    StructuredInvestigationPlanner,
    StructuredProjectVerifier,
    _PlanDraft,
    _PlanRevisionDraft,
    _ObservationDraft,
    _VerificationDraft,
    _deterministic_iso_date_facts,
    _execution_output_type,
    _generated_content_output_type,
    _execution_inventory_payload,
    _inventory_payload,
    _observed_github_repository_paths,
    _planning_evidence_payload,
    _revision_output_type,
)
from personal_agent.application.investigation_project.ports import EvidenceMaterial
from personal_agent.capabilities.contracts.model import StructuredModelResponse
from personal_agent.capabilities.inventory import (
    A2AAgentInventoryItem,
    LocalToolInventoryItem,
    RuntimeCapabilityInventory,
)
from personal_agent.domain.investigation_project import (
    AcceptedPlanVersion,
    AgentExecutionOperation,
    CapabilityContract,
    DecisionFeedback,
    DerivedRequirement,
    EvidenceRef,
    ExecutionRef,
    InvestigationProject,
    InvestigationProjectDefinition,
    PlanProposal,
    ProjectUsage,
    ReplanRequest,
    RequirementMapping,
    SubGoalDefinitionVersion,
    SubGoalExecutionProposal,
    SubGoalVersionRef,
    ToolExecutionOperation,
    UserRequirement,
    UserRequirementVersion,
    WaitingReason,
    canonical_digest,
)
from personal_agent.kernel.contracts.scope import (
    ExecutionScope,
    AuthenticatedPrincipal,
)


def _subgoal(logical_id: str, objective: str) -> SubGoalDefinitionVersion:
    temporary = SubGoalDefinitionVersion(
        logical_subgoal_id=logical_id,
        subgoal_version=1,
        definition_digest="0" * 64,
        objective=objective,
        required_output=f"{logical_id} evidence",
        capability_contract=CapabilityContract(
            contract_id=f"contract:{logical_id}",
            operation="web_search",
            semantic_domain="investigation",
            resource_type="evidence",
            allowed_execution_kinds=("tool",),
        ),
    )
    return temporary.model_copy(
        update={"definition_digest": subgoal_definition_digest(temporary)}
    )


def _project_with_frozen_execution() -> tuple[
    InvestigationProject,
    SubGoalDefinitionVersion,
]:
    requirement = UserRequirement(
        requirement_id="release-change",
        statement="Find a formal release change.",
        acceptance_contract="Cite the formal source and date.",
    )
    definition = InvestigationProjectDefinition(
        project_id="project-1",
        principal=AuthenticatedPrincipal(
            tenant_id="tenant-1",
            user_id="user-1",
        ),
        title="Release investigation",
        goal="Find a formal release change.",
        user_requirements=UserRequirementVersion(
            version=1,
            requirements=(requirement,),
        ),
        create_idempotency_key="create-1",
    )
    frozen = _subgoal("initial-search", "Search for the release.")
    initial = PlanProposal(
        project_id=definition.project_id,
        based_on_event_sequence=0,
        capability_snapshot_revision="capability-v1",
        revision_reason="initial",
        subgoals=(frozen,),
        requirement_mappings=(
            RequirementMapping(
                requirement_id=requirement.requirement_id,
                logical_subgoal_ids=(frozen.logical_subgoal_id,),
            ),
        ),
    )
    project = InvestigationProject(
        definition=definition,
        accepted_plan=AcceptedPlanVersion(
            plan_version=1,
            proposal=initial,
            plan_digest=canonical_digest(initial),
        ),
        event_sequence=7,
    )
    project.execution_refs[(frozen.logical_subgoal_id, frozen.subgoal_version)] = (
        ExecutionRef(
            execution_id="execution-1",
            execution_kind="tool",
            owner_ref="proposal-1",
            execution_digest="e" * 64,
        )
    )
    project.waiting_reasons[(frozen.logical_subgoal_id, frozen.subgoal_version)] = (
        WaitingReason(
            logical_subgoal_id=frozen.logical_subgoal_id,
            subgoal_version=frozen.subgoal_version,
            reason="verification_repair",
            recovery_authority="planner",
            detail="The source is not a formal release.",
        )
    )
    return project, frozen


def _project_with_agent_subgoal() -> tuple[
    InvestigationProject,
    SubGoalDefinitionVersion,
    RuntimeCapabilityInventory,
]:
    project, original_subgoal = _project_with_frozen_execution()
    agent_subgoal = original_subgoal.model_copy(update={
        "capability_contract": CapabilityContract(
            contract_id="contract:gpt-researcher",
            operation="gpt_researcher",
            semantic_domain="external_research",
            resource_type="report",
            allowed_execution_kinds=("agent",),
        ),
    })
    agent_subgoal = agent_subgoal.model_copy(update={
        "definition_digest": subgoal_definition_digest(agent_subgoal),
    })
    revised_plan = project.accepted_plan.proposal.model_copy(update={
        "subgoals": (agent_subgoal,),
    })
    project.accepted_plan = AcceptedPlanVersion(
        plan_version=1,
        proposal=revised_plan,
        plan_digest=canonical_digest(revised_plan),
    )
    inventory = RuntimeCapabilityInventory(
        local_tools=(),
        mcp_connectors=(),
        a2a_agents=(A2AAgentInventoryItem(
            agent_id="gpt_researcher",
            semantic_domains=("external_research",),
            resource_types=("report",),
            operations=("gpt_researcher",),
            implementation_present=True,
            configuration_state="enabled",
            discovery_state="registered_profile",
            max_runtime_seconds=240,
        ),),
    )
    return project, agent_subgoal, inventory


class _RevisionModel:
    def __init__(self) -> None:
        self.request = None

    def generate(self, request):
        self.request = request
        return StructuredModelResponse(
            value=request.output_type.model_validate({
                "independent_repair_subgoals": [{
                    "logical_subgoal_id": "initial-search-repair",
                    "objective": "Find the formal release source.",
                    "required_output": "Formal source URL and release date.",
                    "repairs_frozen_logical_subgoal_ids": ["initial-search"],
                    "capability_contract": {
                        "contract_id": "contract:initial-search-repair",
                        "operation": "web_search",
                        "semantic_domain": "investigation",
                        "resource_type": "evidence",
                        "allowed_execution_kinds": ["tool"],
                    },
                }],
            }),
            model="test-model",
            latency_ms=1,
            total_tokens=10,
        )


class _InitialCapabilityPlannerModel:
    def __init__(self) -> None:
        self.request = None

    def generate(self, request):
        self.request = request
        return StructuredModelResponse(
            value=request.output_type.model_validate({
                "subgoals": [
                    {
                        "logical_subgoal_id": "multi-source-research",
                        "objective": "Research all named official sources.",
                        "required_output": (
                            "Evidence-backed comparison covering every named source."
                        ),
                        "capability_contract": {
                            "contract_id": "contract:multi-source-research",
                            "operation": "gpt_researcher",
                            "semantic_domain": "external_research",
                            "resource_type": "report",
                            "allowed_execution_kinds": ["agent"],
                        },
                    },
                    {
                        "logical_subgoal_id": "report",
                        "objective": "Synthesize the final report.",
                        "depends_on": ["multi-source-research"],
                        "required_output": "Final report with source URLs.",
                        "capability_contract": {
                            "contract_id": "contract:report",
                            "operation": "synthesize",
                            "semantic_domain": "synthesis",
                            "resource_type": "",
                            "allowed_execution_kinds": ["synthesis"],
                        },
                    },
                ],
                "requirement_mappings": [{
                    "requirement_id": "release-change",
                    "logical_subgoal_ids": [
                        "multi-source-research",
                        "report",
                    ],
                }],
            }),
            model="test-model",
            latency_ms=1,
            total_tokens=10,
        )


def _plan_draft_payload() -> dict[str, object]:
    return {
        "derived_requirements": [{
            "requirement_id": "supporting-context",
            "statement": "Capture contextual evidence that strengthens the answer.",
            "acceptance_contract": "Cite one relevant official source.",
            "completion_relevance": "supporting",
            "mapped_logical_subgoal_ids": ["research"],
        }],
        "subgoals": [{
            "logical_subgoal_id": "research",
            "objective": "Collect the supporting official context.",
            "required_output": "One cited supporting observation.",
            "capability_contract": {
                "contract_id": "contract:research",
                "operation": "web_search",
                "semantic_domain": "investigation",
                "resource_type": "evidence",
                "allowed_execution_kinds": ["tool"],
            },
        }],
        "requirement_mappings": [{
            "requirement_id": "primary-result",
            "logical_subgoal_ids": ["research"],
        }],
    }


def test_plan_draft_reuses_canonical_requirement_relevance_contract() -> None:
    payload = _plan_draft_payload()

    draft = _PlanDraft.model_validate(payload)
    proposal = StructuredInvestigationPlanner._materialize(
        draft,
        project_id="project-1",
        based_on_event_sequence=0,
        capability_revision="capability-v1",
        revision_reason="initial",
    )

    assert proposal.derived_requirements[0].completion_relevance == "supporting"
    invalid_payload = {
        **payload,
        "derived_requirements": [{
            **payload["derived_requirements"][0],
            "completion_relevance": "informational",
        }],
    }
    with pytest.raises(ValueError, match="Input should be 'required' or 'supporting'"):
        _PlanDraft.model_validate(invalid_payload)


@pytest.mark.parametrize(
    ("field", "expected"),
    (
        ("subgoals", "logical subgoal ids must be unique"),
        ("derived_requirements", "derived requirement ids must be unique"),
        ("requirement_mappings", "requirement mapping ids must be unique"),
    ),
)
def test_plan_draft_rejects_duplicate_identity_fields_before_materialization(
    field: str,
    expected: str,
) -> None:
    payload = _plan_draft_payload()
    payload[field] = [*payload[field], payload[field][0]]  # type: ignore[index]

    with pytest.raises(ValueError, match=expected):
        _PlanDraft.model_validate(payload)


def test_plan_revision_drafts_reject_duplicate_logical_ids_before_materialization() -> None:
    payload = _plan_draft_payload()
    subgoal = payload["subgoals"][0]  # type: ignore[index]
    mapping = payload["requirement_mappings"]  # type: ignore[index]

    with pytest.raises(ValueError, match="logical subgoal ids must be unique"):
        _PlanRevisionDraft.model_validate({
            "revisable_subgoals": [subgoal, subgoal],
            "requirement_mappings": mapping,
        })

    repair = {
        **subgoal,
        "repairs_frozen_logical_subgoal_ids": ["frozen-search"],
    }
    with pytest.raises(ValueError, match="logical subgoal ids must be unique"):
        _PlanRevisionDraft.model_validate({
            "revisable_subgoals": [subgoal],
            "independent_repair_subgoals": [repair],
            "requirement_mappings": mapping,
        })


def test_semantic_and_repair_revisions_share_one_canonical_draft_model() -> None:
    inventory = RuntimeCapabilityInventory(
        local_tools=(),
        mcp_connectors=(),
        a2a_agents=(),
    )

    semantic_revision_type = _revision_output_type(
        inventory,
        repair_gap_ids=(),
    )
    repair_revision_type = _revision_output_type(
        inventory,
        repair_gap_ids=("frozen-search",),
    )

    assert issubclass(semantic_revision_type, _PlanRevisionDraft)
    assert issubclass(repair_revision_type, _PlanRevisionDraft)
    assert not hasattr(investigation_model_ports, "_RepairPlanRevisionDraft")


@pytest.mark.parametrize(
    ("field", "expected"),
    (
        ("subgoals", "logical subgoal ids must be unique"),
        ("requirement_mappings", "requirement mapping ids must be unique"),
    ),
)
def test_plan_admission_retains_typed_duplicate_identity_guard(
    field: str,
    expected: str,
) -> None:
    project, _ = _project_with_frozen_execution()
    proposal = project.accepted_plan.proposal
    duplicate_values = (*getattr(proposal, field), getattr(proposal, field)[0])
    proposal = proposal.model_copy(update={
        "based_on_event_sequence": project.event_sequence,
        field: duplicate_values,
    })

    with pytest.raises(ProposalRejected, match=expected) as exc_info:
        PlanAdmission().accept(
            project,
            proposal,
            capabilities=RuntimeCapabilityInventory(
                local_tools=(),
                mcp_connectors=(),
                a2a_agents=(),
            ),
        )

    assert exc_info.value.feedback.repairable_fields == (field,)


def test_initial_planner_uses_declared_multi_source_agent_scope_without_losing_repair_space() -> None:
    project, _ = _project_with_frozen_execution()
    model = _InitialCapabilityPlannerModel()
    capabilities = RuntimeCapabilityInventory(
        local_tools=(),
        mcp_connectors=(),
        a2a_agents=(A2AAgentInventoryItem(
            agent_id="gpt_researcher",
            description=(
                "Research authoritative web sources and return an evidence-backed "
                "report for parent synthesis."
            ),
            semantic_domains=("external_research",),
            resource_types=("report",),
            operations=("gpt_researcher",),
            implementation_present=True,
            configuration_state="enabled",
            discovery_state="registered_profile",
        ),),
    )

    decision = StructuredInvestigationPlanner(model).propose_initial(
        project.definition,
        based_on_event_sequence=0,
        repair_request=None,
        capabilities=capabilities,
        capability_revision="capability-v1",
    )

    assert model.request is not None
    instruction = model.request.messages[0]["content"]
    assert "Do not split named sources merely because there are several" in instruction
    assert "Do not preallocate speculative repair SubGoals" in instruction
    assert sum(
        "agent" in item.capability_contract.allowed_execution_kinds
        for item in decision.value.subgoals
    ) == 1


class _VerifierModel:
    def __init__(self) -> None:
        self.request = None

    def generate(self, request):
        self.request = request
        return StructuredModelResponse(
            value=request.output_type.model_validate({
                "satisfied": False,
                "feedback": "Read an admitted formal release page with an explicit date.",
                "observations": [],
            }),
            model="test-model",
            latency_ms=1,
            total_tokens=10,
        )


class _ExecutionProposalModel:
    def __init__(self) -> None:
        self.request = None

    def generate(self, request):
        self.request = request
        return StructuredModelResponse(
            value=request.output_type.model_validate({
                "operation": {
                    "kind": "tool",
                    "tool_name": "web_search",
                    "typed_arguments": {
                        "query": "official release source",
                        "limit": 10,
                        "scrape": True,
                    },
                    "expected_artifact_type": "evidence",
                },
            }),
            model="test-model",
            latency_ms=1,
            total_tokens=10,
        )


class _AgentExecutionProposalModel:
    def __init__(self) -> None:
        self.request = None

    def generate(self, request):
        self.request = request
        return StructuredModelResponse(
            value=request.output_type.model_validate({
                "operation": {
                    "kind": "agent",
                    "agent_id": "gpt_researcher",
                    "expected_artifact_types": ["report"],
                    "token_budget": 4_000,
                    "cost_budget": 1.0,
                    "time_budget_seconds": 240,
                },
            }),
            model="test-model",
            latency_ms=1,
            total_tokens=10,
        )


def test_execution_proposer_compiles_agent_goal_from_accepted_subgoal() -> None:
    project, subgoal, inventory = _project_with_agent_subgoal()
    model = _AgentExecutionProposalModel()

    decision = StructuredExecutionProposer(model).propose(
        project,
        subgoal,
        evidence_material=(),
        execution_scope=ExecutionScope(
            principal=project.definition.principal,
            thread_id=project.definition.project_id,
            task_id=subgoal.logical_subgoal_id,
            project_id=project.definition.project_id,
            plan_version=project.accepted_plan.plan_version,
            logical_subgoal_id=subgoal.logical_subgoal_id,
            subgoal_version=subgoal.subgoal_version,
            execution_id="agent-proposal-test",
        ),
        capabilities=inventory,
    )

    assert model.request is not None
    assert "bounded_sub_goal" not in json.dumps(
        model.request.output_type.model_json_schema()
    )
    assert decision.value.operation.kind == "agent"
    assert decision.value.operation.bounded_sub_goal == (
        "Objective:\nSearch for the release.\n\n"
        "Required output:\ninitial-search evidence"
    )


class _CaptureProposalModel:
    def __init__(self, candidate_id: str) -> None:
        self.candidate_id = candidate_id
        self.request = None

    def generate(self, request):
        self.request = request
        return StructuredModelResponse(
            value=request.output_type.model_validate({
                "operation": {
                    "kind": "tool",
                    "tool_name": "capture_url",
                    "typed_arguments": {
                        "candidate_id": self.candidate_id,
                    },
                    "expected_artifact_type": "web_page",
                },
            }),
            model="test-model",
            latency_ms=1,
            total_tokens=10,
        )


def test_execution_proposer_receives_durable_local_admission_feedback() -> None:
    project, frozen = _project_with_frozen_execution()
    feedback = DecisionFeedback(
        reason="selected Tool is outside the accepted SubGoal capability contract",
        repairable_fields=("operation",),
        immutable_fields=("project_id", "plan_version", "logical_subgoal_id"),
        required_repair="Select web_search.",
        revision_scope=(frozen.logical_subgoal_id,),
    )
    project.execution_proposal_feedback[
        (frozen.logical_subgoal_id, frozen.subgoal_version)
    ] = [feedback]
    model = _ExecutionProposalModel()

    StructuredExecutionProposer(model).propose(
        project,
        frozen,
        evidence_material=(),
        execution_scope=ExecutionScope(
            principal=project.definition.principal,
            thread_id=project.definition.project_id,
            task_id=frozen.logical_subgoal_id,
            project_id=project.definition.project_id,
            plan_version=project.accepted_plan.plan_version,
            logical_subgoal_id=frozen.logical_subgoal_id,
            subgoal_version=frozen.subgoal_version,
            execution_id="proposal-test",
        ),
        capabilities=RuntimeCapabilityInventory(
            local_tools=(
                LocalToolInventoryItem(
                    tool_name="web_search",
                    exposure="public_agent",
                    risk_level="low",
                    input_schema={"type": "object"},
                    provider_availability="not_observed",
                ),
            ),
            mcp_connectors=(),
            a2a_agents=(),
        ),
    )

    payload = json.loads(model.request.messages[1]["content"])
    assert payload["prior_execution_proposal_feedback"] == [
        feedback.model_dump(mode="json")
    ]
    assert payload["remaining_agent_budget"] == {
        "tokens": 20_000,
        "cost": 20.0,
    }


def test_project_budget_ledger_derives_remaining_agent_budget_from_committed_facts(
) -> None:
    project, _ = _project_with_frozen_execution()
    project.usages.append(ProjectUsage(
        category="external_delegation",
        reservation_id="charged-agent",
        tokens=3_000,
        cost=2.5,
        agent_calls=1,
    ))
    project.active_reservations["reserved-planning"] = ProjectUsage(
        category="planning",
        reservation_id="reserved-planning",
        tokens=5_000,
        cost=1.0,
    )

    ledger = ProjectBudgetLedger()

    assert ledger.remaining_tokens(
        project,
        category="external_delegation",
    ) == 17_000
    assert ledger.remaining_cost(project) == 16.5


def test_execution_proposer_excludes_previously_failed_capture_url() -> None:
    project, frozen = _project_with_frozen_execution()
    old_url = "https://example.test/invalid-release"
    new_url = "https://example.test/formal-release"
    old_operation = ToolExecutionOperation(
        tool_name="capture_url",
        typed_arguments={"url": old_url},
        expected_artifact_type="web_page",
    )
    old_binding = {
        "project_id": project.definition.project_id,
        "plan_version": project.accepted_plan.plan_version,
        "logical_subgoal_id": frozen.logical_subgoal_id,
        "subgoal_version": frozen.subgoal_version,
        "based_on_event_sequence": 4,
        "proposal_id": "old-proposal",
        "operation": old_operation.model_dump(mode="json"),
    }
    project.accepted_execution_proposals[
        (frozen.logical_subgoal_id, frozen.subgoal_version)
    ] = SubGoalExecutionProposal(
        **old_binding,
        proposal_digest=canonical_digest(old_binding),
    )
    temporary_capture = SubGoalDefinitionVersion(
        logical_subgoal_id="initial-search-repair",
        subgoal_version=1,
        definition_digest="0" * 64,
        objective="Read another formal release candidate.",
        required_output="Formal release page.",
        capability_contract=CapabilityContract(
            contract_id="capture-url",
            operation="capture_url",
            semantic_domain="web",
            resource_type="web_page",
            allowed_execution_kinds=("tool",),
        ),
        repairs_frozen_subgoals=(
            SubGoalVersionRef(
                logical_subgoal_id=frozen.logical_subgoal_id,
                subgoal_version=frozen.subgoal_version,
            ),
        ),
    )
    capture = temporary_capture.model_copy(update={
        "definition_digest": subgoal_definition_digest(temporary_capture),
    })
    revised_proposal = project.accepted_plan.proposal.model_copy(update={
        "based_on_event_sequence": project.event_sequence,
        "revision_reason": "try another candidate",
        "subgoals": (frozen, capture),
        "requirement_mappings": (
            RequirementMapping(
                requirement_id="release-change",
                logical_subgoal_ids=(capture.logical_subgoal_id,),
            ),
        ),
    })
    project.accepted_plan = AcceptedPlanVersion(
        plan_version=2,
        proposal=revised_proposal,
        plan_digest=canonical_digest(revised_proposal),
    )
    evidence = EvidenceRef(
        evidence_id="candidate-set",
        execution_ref=project.execution_refs[
            (frozen.logical_subgoal_id, frozen.subgoal_version)
        ],
        source="tool:web_search",
        content_digest="c" * 64,
    )
    model = _CaptureProposalModel("url_candidate_01")

    decision = StructuredExecutionProposer(model).propose(
        project,
        capture,
        evidence_material=(
            EvidenceMaterial(
                reference=evidence,
                content=json.dumps({
                    "data": {
                        "results": [
                            {"url": old_url},
                            {"url": new_url},
                        ],
                    },
                }),
            ),
        ),
        execution_scope=ExecutionScope(
            principal=project.definition.principal,
            thread_id=project.definition.project_id,
            task_id=capture.logical_subgoal_id,
            project_id=project.definition.project_id,
            plan_version=project.accepted_plan.plan_version,
            logical_subgoal_id=capture.logical_subgoal_id,
            subgoal_version=capture.subgoal_version,
            execution_id="capture-proposal-test",
        ),
        capabilities=RuntimeCapabilityInventory(
            local_tools=(
                LocalToolInventoryItem(
                    tool_name="capture_url",
                    exposure="public_agent",
                    risk_level="low",
                    input_schema={"type": "object"},
                    provider_availability="not_observed",
                ),
            ),
            mcp_connectors=(),
            a2a_agents=(),
        ),
    )

    payload = json.loads(model.request.messages[1]["content"])
    assert payload["observed_url_locators"] == [new_url]
    assert payload["observed_url_candidates"] == [{
        "candidate_id": "url_candidate_01",
        "url": new_url,
    }]
    assert decision.value.operation.typed_arguments == {"url": new_url}


def test_observed_url_locators_include_agent_artifact_text_urls() -> None:
    project, _ = _project_with_frozen_execution()
    official_url = "https://a2a-protocol.org/latest/"
    material = EvidenceMaterial(
        reference=EvidenceRef(
            evidence_id="agent-report",
            execution_ref=ExecutionRef(
                execution_id="agent-execution",
                execution_kind="agent",
                owner_ref="agent-proposal",
                execution_digest="a" * 64,
            ),
            source="agent:gpt_researcher",
            content_digest="b" * 64,
        ),
        content=(
            "The admitted Agent report cites the official protocol page "
            f"{official_url} for direct verification."
        ),
    )

    assert observed_url_locators(project, (material,)) == (official_url,)


def test_subgoal_verifier_rejects_all_insufficient_observations_as_success() -> None:
    project, frozen = _project_with_frozen_execution()
    model = _VerifierModel()

    decision = StructuredProjectVerifier(model).verify_subgoal(
        project,
        frozen,
        (),
        evidence_material=(),
        execution_scope=ExecutionScope(
            principal=project.definition.principal,
            thread_id=project.definition.project_id,
            task_id=frozen.logical_subgoal_id,
            project_id=project.definition.project_id,
            plan_version=1,
            logical_subgoal_id=frozen.logical_subgoal_id,
            subgoal_version=frozen.subgoal_version,
            execution_id="verification-1",
        ),
    )

    assert decision.value.satisfied is False
    assert model.request is not None
    system_instruction = model.request.messages[0]["content"]
    assert "If every observation says a candidate is" in system_instruction
    assert "return satisfied=false with actionable feedback" in system_instruction


def test_unsatisfied_verification_schema_requires_actionable_feedback() -> None:
    with pytest.raises(ValueError, match="actionable repair feedback"):
        _VerificationDraft.model_validate({
            "satisfied": False,
            "feedback": " ",
        })


def test_verifier_observation_schema_rejects_missing_evidence_binding() -> None:
    with pytest.raises(ValueError, match="at least 1 item"):
        _ObservationDraft.model_validate({
            "statement": "This observation has no supporting project evidence.",
            "evidence_refs": [],
        })


def test_synthesis_schema_materializes_required_lineage_before_long_content() -> None:
    reference = EvidenceRef(
        evidence_id="evidence-1",
        execution_ref=ExecutionRef(
            execution_id="execution-1",
            execution_kind="agent",
            owner_ref="proposal-1",
            execution_digest="e" * 64,
        ),
        source="agent:gpt_researcher",
        content_digest="c" * 64,
    )

    schema = _generated_content_output_type((
        EvidenceMaterial(reference=reference, content="bounded evidence"),
    )).model_json_schema()
    fields = list(schema["properties"])

    assert fields.index("evidence_refs") < fields.index("content")
    assert "evidence_refs" in schema["required"]


def test_iso_date_facts_compare_evidence_dates_against_inclusive_window() -> None:
    reference = EvidenceRef(
        evidence_id="evidence-1",
        execution_ref=ExecutionRef(
            execution_id="execution-1",
            execution_kind="tool",
            owner_ref="proposal-1",
            execution_digest="e" * 64,
        ),
        source="tool:web_search",
        content_digest="c" * 64,
    )

    facts = _deterministic_iso_date_facts(
        "调研 2025-03-01 至 2025-06-30 发布的规范。",
        (
            EvidenceMaterial(
                reference=reference,
                content="releases: 2025-02-28, 2025-06-18, 2025-06-30, 2025-11-25",
            ),
        ),
    )

    assert facts is not None
    assert facts["inclusive_start"] == "2025-03-01"
    assert facts["inclusive_end"] == "2025-06-30"
    assert facts["evidence"] == [{
        "project_evidence_id": "evidence-1",
        "within_inclusive_window": ["2025-06-18", "2025-06-30"],
        "outside_inclusive_window": ["2025-02-28", "2025-11-25"],
        "invalid_iso_dates": [],
    }]


def test_observed_github_repository_paths_preserve_current_owner_identity() -> None:
    assert _observed_github_repository_paths((
        "https://github.com/a2aproject/A2A/issues/142",
        "https://github.com/a2aproject/A2A/releases",
        "https://example.test/a2aproject/A2A",
    )) == ("github.com/a2aproject/A2A",)


def test_planning_evidence_materializes_bounded_candidates_not_full_pages() -> None:
    reference = EvidenceRef(
        evidence_id="evidence-1",
        execution_ref=ExecutionRef(
            execution_id="execution-1",
            execution_kind="tool",
            owner_ref="proposal-1",
            execution_digest="e" * 64,
        ),
        source="tool:web_search",
        content_digest="c" * 64,
    )
    long_snippet = "release evidence " * 200

    payload = _planning_evidence_payload((
        EvidenceMaterial(
            reference=reference,
            content=json.dumps({
                "data": {
                    "results": [{
                        "title": "Official releases 2025-06-18",
                        "url": "https://example.test/releases",
                        "published_at": None,
                        "snippet": long_snippet,
                    }],
                },
                "tool": "web_search",
            }),
        ),
    ))

    candidate = payload[0]["web_search_candidates"][0]
    assert candidate["url"] == "https://example.test/releases"
    assert candidate["explicit_dates_in_title_or_snippet"] == ["2025-06-18"]
    assert len(candidate["bounded_snippet"]) == 600
    assert long_snippet not in json.dumps(payload)


def test_revision_planner_compiles_frozen_subgoal_from_canonical_project() -> None:
    project, frozen = _project_with_frozen_execution()
    model = _RevisionModel()
    planner = StructuredInvestigationPlanner(model)
    request_payload = {
        "trigger_kind": "verification_gap",
        "trigger_ref": "verification-1",
        "affected_logical_subgoal_ids": (frozen.logical_subgoal_id,),
    }
    request = ReplanRequest(
        **request_payload,
        trigger_digest=canonical_digest(request_payload),
    )

    decision = planner.propose_revision(
        project,
        request,
        evidence_material=(),
        capabilities=RuntimeCapabilityInventory(
            local_tools=(
                LocalToolInventoryItem(
                    tool_name="web_search",
                    semantic_domains=("investigation",),
                    resource_types=("evidence",),
                    operations=("web_search",),
                    exposure="public_agent",
                    risk_level="low",
                    input_schema={"type": "object"},
                    provider_availability="not_observed",
                ),
            ),
            mcp_connectors=(),
            a2a_agents=(),
        ),
        capability_revision="capability-v1",
    )

    assert model.request is not None
    assert "revisable_subgoals" in model.request.output_type.model_fields
    assert "independent_repair_subgoals" in model.request.output_type.model_fields
    assert "subgoals" not in model.request.output_type.model_fields
    schema = model.request.output_type.model_json_schema()
    executable_contract = schema["$defs"][
        "_PlannerExecutableCapabilityContract0"
    ]["properties"]
    assert executable_contract["operation"]["const"] == "web_search"
    assert executable_contract["semantic_domain"]["const"] == "investigation"
    assert executable_contract["resource_type"]["const"] == "evidence"
    assert executable_contract["allowed_execution_kinds"]["items"]["const"] == (
        "tool"
    )
    repair_properties = schema["$defs"][
        "_AdmittedIndependentRepairSubGoalDraft"
    ]["properties"]
    assert repair_properties["logical_subgoal_id"]["const"] == (
        "initial-search-repair"
    )
    assert repair_properties[
        "repairs_frozen_logical_subgoal_ids"
    ]["items"]["const"] == frozen.logical_subgoal_id
    visible_payload = json.loads(model.request.messages[1]["content"])
    assert visible_payload["frozen_subgoal_refs_read_only"] == [{
        "logical_subgoal_id": frozen.logical_subgoal_id,
        "subgoal_version": frozen.subgoal_version,
        "definition_digest": frozen.definition_digest,
    }]
    assert visible_payload["forbidden_logical_subgoal_ids"] == [
        frozen.logical_subgoal_id
    ]
    assert visible_payload["admitted_evidence_candidate_context"] == []
    assert visible_payload["required_independent_repairs"] == [{
        "frozen_logical_subgoal_id": frozen.logical_subgoal_id,
        "frozen_subgoal_version": frozen.subgoal_version,
        "required_repair_logical_subgoal_id": "initial-search-repair",
        "verification_gap": "The source is not a formal release.",
        "capability_contract_template": (
            frozen.capability_contract.model_dump(mode="json")
        ),
    }]
    assert visible_payload["repair_candidate_context"] == [{
        "frozen_gap_ref": {
            "logical_subgoal_id": frozen.logical_subgoal_id,
            "subgoal_version": frozen.subgoal_version,
        },
        "required_repair_logical_subgoal_id": "initial-search-repair",
        "candidate_evidence": [],
    }]
    assert decision.value.subgoals[0] == frozen
    assert decision.value.subgoals[1].logical_subgoal_id == "initial-search-repair"
    assert decision.value.subgoals[1].repairs_frozen_subgoals == (
        SubGoalVersionRef(
            logical_subgoal_id=frozen.logical_subgoal_id,
            subgoal_version=frozen.subgoal_version,
        ),
    )
    assert decision.value.requirement_mappings[0].logical_subgoal_ids == (
        "initial-search-repair",
    )
    assert PlanAdmission().accept(
        project,
        decision.value,
        capabilities=RuntimeCapabilityInventory(
            local_tools=(
                LocalToolInventoryItem(
                    tool_name="web_search",
                    exposure="public_agent",
                    risk_level="low",
                    input_schema={"type": "object"},
                    provider_availability="not_observed",
                ),
            ),
            mcp_connectors=(),
            a2a_agents=(),
        ),
    ) is not None


def test_plan_admission_rejects_repair_mapping_without_canonical_lineage() -> None:
    project, frozen = _project_with_frozen_execution()
    repair = _subgoal(
        "initial-search-repair",
        "Find the formal release source.",
    )
    proposal = PlanProposal(
        project_id=project.definition.project_id,
        based_on_event_sequence=project.event_sequence,
        capability_snapshot_revision="capability-v1",
        revision_reason="repair verification gap",
        subgoals=(frozen, repair),
        requirement_mappings=(
            RequirementMapping(
                requirement_id="release-change",
                logical_subgoal_ids=(repair.logical_subgoal_id,),
            ),
        ),
    )

    with pytest.raises(ProposalRejected, match="canonical repair lineage"):
        PlanAdmission().accept(
            project,
            proposal,
            capabilities=RuntimeCapabilityInventory(
                local_tools=(
                    LocalToolInventoryItem(
                        tool_name="web_search",
                        exposure="public_agent",
                        risk_level="low",
                        input_schema={"type": "object"},
                        provider_availability="not_observed",
                    ),
                ),
                mcp_connectors=(),
                a2a_agents=(),
            ),
        )


def test_repair_lineage_ignores_removed_derived_requirement_mapping() -> None:
    project, frozen = _project_with_frozen_execution()
    old_derived = DerivedRequirement(
        requirement_id="old-derived",
        statement="Old planner-owned requirement.",
        acceptance_contract="No longer required by the revision.",
    )
    previous = project.accepted_plan.proposal.model_copy(update={
        "derived_requirements": (old_derived,),
        "requirement_mappings": (
            *project.accepted_plan.proposal.requirement_mappings,
            RequirementMapping(
                requirement_id=old_derived.requirement_id,
                logical_subgoal_ids=(frozen.logical_subgoal_id,),
            ),
        ),
    })
    project.accepted_plan = project.accepted_plan.model_copy(update={
        "proposal": previous,
        "plan_digest": canonical_digest(previous),
    })
    temporary_repair = _subgoal(
        "initial-search-repair",
        "Find the formal release source.",
    ).model_copy(update={
        "repairs_frozen_subgoals": (
            SubGoalVersionRef(
                logical_subgoal_id=frozen.logical_subgoal_id,
                subgoal_version=frozen.subgoal_version,
            ),
        ),
    })
    repair = temporary_repair.model_copy(update={
        "definition_digest": subgoal_definition_digest(temporary_repair),
    })
    proposal = PlanProposal(
        project_id=project.definition.project_id,
        based_on_event_sequence=project.event_sequence,
        capability_snapshot_revision="capability-v1",
        revision_reason="remove stale derived requirement",
        subgoals=(frozen, repair),
        requirement_mappings=(
            RequirementMapping(
                requirement_id="release-change",
                logical_subgoal_ids=(repair.logical_subgoal_id,),
            ),
        ),
    )

    assert PlanAdmission().accept(
        project,
        proposal,
        capabilities=RuntimeCapabilityInventory(
            local_tools=(
                LocalToolInventoryItem(
                    tool_name="web_search",
                    exposure="public_agent",
                    risk_level="low",
                    input_schema={"type": "object"},
                    provider_availability="not_observed",
                ),
            ),
            mcp_connectors=(),
            a2a_agents=(),
        ),
    ) is not None


def test_repair_revision_preserves_omitted_nonfrozen_subgoals() -> None:
    frozen = _subgoal("initial-search", "Search for the release.")
    pending = _subgoal("final-report", "Write the final report.").model_copy(update={
        "depends_on": (frozen.logical_subgoal_id,),
    })
    pending = pending.model_copy(update={
        "definition_digest": subgoal_definition_digest(pending),
    })
    draft = _PlanRevisionDraft.model_validate({
        "independent_repair_subgoals": [{
            "logical_subgoal_id": "initial-search-repair",
            "objective": "Read the formal release source.",
            "required_output": "Formal source URL and release date.",
            "repairs_frozen_logical_subgoal_ids": ["initial-search"],
            "capability_contract": {
                "contract_id": "capture_url",
                "operation": "capture_url",
                "semantic_domain": "web",
                "resource_type": "web_page",
                "allowed_execution_kinds": ["tool"],
            },
        }],
    })

    proposal = StructuredInvestigationPlanner._materialize_revision(
        draft,
        project_id="project-1",
        based_on_event_sequence=8,
        capability_revision="capability-v1",
        revision_reason="repair-1",
        frozen_subgoals=(frozen,),
        previous_subgoals=(frozen, pending),
        previous_requirement_mappings=(
            RequirementMapping(
                requirement_id="release-change",
                logical_subgoal_ids=("initial-search", "final-report"),
            ),
        ),
        previous_derived_requirement_ids=(),
        frozen_gap_ids=("initial-search",),
    )

    assert [
        item.logical_subgoal_id for item in proposal.subgoals
    ] == ["initial-search", "final-report", "initial-search-repair"]
    preserved_pending = proposal.subgoals[1]
    assert preserved_pending.depends_on == ("initial-search",)
    assert preserved_pending.subgoal_version == 1
    assert preserved_pending.supersedes_version is None
    assert proposal.requirement_mappings[0].logical_subgoal_ids == (
        "initial-search-repair",
        "final-report",
    )


def test_execution_admission_rejects_exact_replay_of_unverified_tool_work() -> None:
    project, frozen = _project_with_frozen_execution()
    operation = ToolExecutionOperation(
        tool_name="capture_url",
        typed_arguments={"url": "https://example.test/release"},
        expected_artifact_type="web_page",
    )
    prior_binding = {
        "project_id": project.definition.project_id,
        "plan_version": 1,
        "logical_subgoal_id": frozen.logical_subgoal_id,
        "subgoal_version": frozen.subgoal_version,
        "based_on_event_sequence": 3,
        "proposal_id": "prior-proposal",
        "operation": operation,
    }
    prior = SubGoalExecutionProposal(
        **prior_binding,
        proposal_digest=canonical_digest({
            **prior_binding,
            "operation": operation.model_dump(mode="json"),
        }),
    )
    project.accepted_execution_proposals[
        (frozen.logical_subgoal_id, frozen.subgoal_version)
    ] = prior
    repair = _subgoal("repair-source", "Read a different formal release source.")
    repair = repair.model_copy(update={
        "capability_contract": CapabilityContract(
            contract_id="capture_url",
            operation="capture_url",
            semantic_domain="web",
            resource_type="web_page",
            allowed_execution_kinds=("tool",),
        ),
    })
    repair = repair.model_copy(update={
        "definition_digest": subgoal_definition_digest(repair),
    })
    current_plan = project.accepted_plan
    assert current_plan is not None
    revised_proposal = current_plan.proposal.model_copy(update={
        "subgoals": (frozen, repair),
        "requirement_mappings": (
            RequirementMapping(
                requirement_id="release-change",
                logical_subgoal_ids=(repair.logical_subgoal_id,),
            ),
        ),
    })
    project.accepted_plan = AcceptedPlanVersion(
        plan_version=2,
        proposal=revised_proposal,
        plan_digest=canonical_digest(revised_proposal),
    )
    binding = {
        "project_id": project.definition.project_id,
        "plan_version": 2,
        "logical_subgoal_id": repair.logical_subgoal_id,
        "subgoal_version": repair.subgoal_version,
        "based_on_event_sequence": project.event_sequence,
        "proposal_id": "repair-proposal",
        "operation": operation,
    }
    repeated = SubGoalExecutionProposal(
        **binding,
        proposal_digest=canonical_digest({
            **binding,
            "operation": operation.model_dump(mode="json"),
        }),
    )

    assert unverified_tool_execution_operations(project) == (operation,)
    with pytest.raises(
        ProposalRejected,
        match="repeats an exact Tool operation",
    ):
        ExecutionProposalAdmission().accept(
            project,
            repair,
            repeated,
            execution_scope=ExecutionScope(
                principal=project.definition.principal,
                project_id=project.definition.project_id,
                plan_version=2,
                logical_subgoal_id=repair.logical_subgoal_id,
                subgoal_version=repair.subgoal_version,
                execution_id="repair-proposal",
            ),
            capabilities=RuntimeCapabilityInventory(
                local_tools=(
                    LocalToolInventoryItem(
                        tool_name="capture_url",
                        semantic_domains=("web",),
                        resource_types=("web_page",),
                        operations=("capture_url",),
                        exposure="workflow_activity",
                        risk_level="low",
                        input_schema={"type": "object"},
                        provider_availability="not_observed",
                    ),
                ),
                mcp_connectors=(),
                a2a_agents=(),
            ),
            observed_url_locators=(operation.typed_arguments["url"],),
        )


def test_execution_admission_returns_typed_capability_missing_feedback() -> None:
    project, subgoal = _project_with_frozen_execution()
    operation = ToolExecutionOperation(
        tool_name="web_search",
        typed_arguments={"query": "formal release notes"},
        expected_artifact_type="web_page",
    )
    binding = {
        "project_id": project.definition.project_id,
        "plan_version": 1,
        "logical_subgoal_id": subgoal.logical_subgoal_id,
        "subgoal_version": subgoal.subgoal_version,
        "based_on_event_sequence": project.event_sequence,
        "proposal_id": "missing-capability-proposal",
        "operation": operation,
    }
    proposal = SubGoalExecutionProposal(
        **binding,
        proposal_digest=canonical_digest({
            **binding,
            "operation": operation.model_dump(mode="json"),
        }),
    )

    with pytest.raises(ProposalRejected) as rejected:
        ExecutionProposalAdmission().accept(
            project,
            subgoal,
            proposal,
            execution_scope=ExecutionScope(
                principal=project.definition.principal,
                project_id=project.definition.project_id,
                plan_version=1,
                logical_subgoal_id=subgoal.logical_subgoal_id,
                subgoal_version=subgoal.subgoal_version,
                execution_id=proposal.proposal_id,
            ),
            capabilities=RuntimeCapabilityInventory(
                local_tools=(),
                mcp_connectors=(),
                a2a_agents=(),
            ),
        )

    assert rejected.value.feedback.reason == "capability missing: web_search"
    assert rejected.value.feedback.disposition == "capability_missing"


def test_execution_admission_rejects_agent_goal_outside_accepted_subgoal() -> None:
    project, subgoal, inventory = _project_with_agent_subgoal()
    operation = AgentExecutionOperation(
        agent_id="gpt_researcher",
        bounded_sub_goal=subgoal.logical_subgoal_id,
        expected_artifact_types=("report",),
        token_budget=4_000,
        cost_budget=1.0,
        time_budget_seconds=240,
    )
    binding = {
        "project_id": project.definition.project_id,
        "plan_version": 1,
        "logical_subgoal_id": subgoal.logical_subgoal_id,
        "subgoal_version": subgoal.subgoal_version,
        "based_on_event_sequence": project.event_sequence,
        "proposal_id": "agent-goal-override",
        "operation": operation,
    }
    proposal = SubGoalExecutionProposal(
        **binding,
        proposal_digest=canonical_digest({
            **binding,
            "operation": operation.model_dump(mode="json"),
        }),
    )

    with pytest.raises(
        ProposalRejected,
        match="agent bounded sub-goal does not match the accepted SubGoal",
    ):
        ExecutionProposalAdmission().accept(
            project,
            subgoal,
            proposal,
            execution_scope=ExecutionScope(
                principal=project.definition.principal,
                project_id=project.definition.project_id,
                plan_version=1,
                logical_subgoal_id=subgoal.logical_subgoal_id,
                subgoal_version=subgoal.subgoal_version,
                execution_id=proposal.proposal_id,
            ),
            capabilities=inventory,
        )


def test_execution_admission_rejects_capture_without_observed_url() -> None:
    project, original_subgoal = _project_with_frozen_execution()
    capture_subgoal = original_subgoal.model_copy(update={
        "capability_contract": CapabilityContract(
            contract_id="capture_url",
            operation="capture_url",
            semantic_domain="web",
            resource_type="web_page",
            allowed_execution_kinds=("tool",),
        ),
    })
    capture_subgoal = capture_subgoal.model_copy(update={
        "definition_digest": subgoal_definition_digest(capture_subgoal),
    })
    revised_plan = project.accepted_plan.proposal.model_copy(update={
        "subgoals": (capture_subgoal,),
    })
    project.accepted_plan = AcceptedPlanVersion(
        plan_version=1,
        proposal=revised_plan,
        plan_digest=canonical_digest(revised_plan),
    )
    operation = ToolExecutionOperation(
        tool_name="capture_url",
        typed_arguments={},
        expected_artifact_type="web_page",
    )
    binding = {
        "project_id": project.definition.project_id,
        "plan_version": 1,
        "logical_subgoal_id": capture_subgoal.logical_subgoal_id,
        "subgoal_version": capture_subgoal.subgoal_version,
        "based_on_event_sequence": project.event_sequence,
        "proposal_id": "capture-without-observed-url",
        "operation": operation,
    }
    proposal = SubGoalExecutionProposal(
        **binding,
        proposal_digest=canonical_digest({
            **binding,
            "operation": operation.model_dump(mode="json"),
        }),
    )

    with pytest.raises(
        ProposalRejected,
        match="capture URL was not observed in user input or execution evidence",
    ):
        ExecutionProposalAdmission().accept(
            project,
            capture_subgoal,
            proposal,
            execution_scope=ExecutionScope(
                principal=project.definition.principal,
                project_id=project.definition.project_id,
                plan_version=1,
                logical_subgoal_id=capture_subgoal.logical_subgoal_id,
                subgoal_version=capture_subgoal.subgoal_version,
                execution_id=proposal.proposal_id,
            ),
            capabilities=RuntimeCapabilityInventory(
                local_tools=(LocalToolInventoryItem(
                    tool_name="capture_url",
                    semantic_domains=("web",),
                    resource_types=("web_page",),
                    operations=("capture_url",),
                    exposure="workflow_activity",
                    risk_level="low",
                    input_schema={"type": "object"},
                    provider_availability="not_observed",
                ),),
                mcp_connectors=(),
                a2a_agents=(),
            ),
            observed_url_locators=(),
        )


def test_execution_admission_rejects_agent_time_budget_above_profile_limit() -> None:
    project, original_subgoal = _project_with_frozen_execution()
    agent_subgoal = original_subgoal.model_copy(update={
        "capability_contract": CapabilityContract(
            contract_id="contract:gpt-researcher",
            operation="gpt_researcher",
            semantic_domain="external_research",
            resource_type="report",
            allowed_execution_kinds=("agent",),
        ),
    })
    agent_subgoal = agent_subgoal.model_copy(update={
        "definition_digest": subgoal_definition_digest(agent_subgoal),
    })
    revised_plan = project.accepted_plan.proposal.model_copy(update={
        "subgoals": (agent_subgoal,),
    })
    project.accepted_plan = AcceptedPlanVersion(
        plan_version=1,
        proposal=revised_plan,
        plan_digest=canonical_digest(revised_plan),
    )
    operation = AgentExecutionOperation(
        agent_id="gpt_researcher",
        bounded_sub_goal=compiled_agent_bounded_sub_goal(agent_subgoal),
        expected_artifact_types=("report",),
        token_budget=4_000,
        cost_budget=1.0,
        time_budget_seconds=1_000_000,
    )
    binding = {
        "project_id": project.definition.project_id,
        "plan_version": 1,
        "logical_subgoal_id": agent_subgoal.logical_subgoal_id,
        "subgoal_version": agent_subgoal.subgoal_version,
        "based_on_event_sequence": project.event_sequence,
        "proposal_id": "oversized-agent-budget",
        "operation": operation,
    }
    proposal = SubGoalExecutionProposal(
        **binding,
        proposal_digest=canonical_digest({
            **binding,
            "operation": operation.model_dump(mode="json"),
        }),
    )

    with pytest.raises(ProposalRejected) as rejected:
        ExecutionProposalAdmission().accept(
            project,
            agent_subgoal,
            proposal,
            execution_scope=ExecutionScope(
                principal=project.definition.principal,
                project_id=project.definition.project_id,
                plan_version=1,
                logical_subgoal_id=agent_subgoal.logical_subgoal_id,
                subgoal_version=agent_subgoal.subgoal_version,
                execution_id=proposal.proposal_id,
            ),
            capabilities=RuntimeCapabilityInventory(
                local_tools=(),
                mcp_connectors=(),
                a2a_agents=(A2AAgentInventoryItem(
                    agent_id="gpt_researcher",
                    semantic_domains=("external_research",),
                    resource_types=("report",),
                    operations=("gpt_researcher",),
                    implementation_present=True,
                    configuration_state="enabled",
                    discovery_state="registered_profile",
                    max_runtime_seconds=240,
                ),),
            ),
        )

    assert rejected.value.feedback.reason == (
        "agent time budget exceeds the registered runtime limit"
    )
    assert rejected.value.feedback.repairable_fields == ("operation",)


@pytest.mark.parametrize(
    ("token_budget", "cost_budget", "expected_reason", "expected_maximum"),
    (
        (
            20_001,
            1.0,
            "agent token budget exceeds the remaining Project delegation budget",
            "20000",
        ),
        (
            4_000,
            20.01,
            "agent cost budget exceeds the remaining Project cost budget",
            "20.0",
        ),
    ),
)
def test_execution_admission_rejects_agent_budget_above_remaining_project_budget(
    token_budget: int,
    cost_budget: float,
    expected_reason: str,
    expected_maximum: str,
) -> None:
    project, original_subgoal = _project_with_frozen_execution()
    agent_subgoal = original_subgoal.model_copy(update={
        "capability_contract": CapabilityContract(
            contract_id="contract:gpt-researcher",
            operation="gpt_researcher",
            semantic_domain="external_research",
            resource_type="report",
            allowed_execution_kinds=("agent",),
        ),
    })
    agent_subgoal = agent_subgoal.model_copy(update={
        "definition_digest": subgoal_definition_digest(agent_subgoal),
    })
    revised_plan = project.accepted_plan.proposal.model_copy(update={
        "subgoals": (agent_subgoal,),
    })
    project.accepted_plan = AcceptedPlanVersion(
        plan_version=1,
        proposal=revised_plan,
        plan_digest=canonical_digest(revised_plan),
    )
    operation = AgentExecutionOperation(
        agent_id="gpt_researcher",
        bounded_sub_goal=compiled_agent_bounded_sub_goal(agent_subgoal),
        expected_artifact_types=("report",),
        token_budget=token_budget,
        cost_budget=cost_budget,
        time_budget_seconds=240,
    )
    binding = {
        "project_id": project.definition.project_id,
        "plan_version": 1,
        "logical_subgoal_id": agent_subgoal.logical_subgoal_id,
        "subgoal_version": agent_subgoal.subgoal_version,
        "based_on_event_sequence": project.event_sequence,
        "proposal_id": "oversized-project-budget",
        "operation": operation,
    }
    proposal = SubGoalExecutionProposal(
        **binding,
        proposal_digest=canonical_digest({
            **binding,
            "operation": operation.model_dump(mode="json"),
        }),
    )

    with pytest.raises(ProposalRejected) as rejected:
        ExecutionProposalAdmission().accept(
            project,
            agent_subgoal,
            proposal,
            execution_scope=ExecutionScope(
                principal=project.definition.principal,
                project_id=project.definition.project_id,
                plan_version=1,
                logical_subgoal_id=agent_subgoal.logical_subgoal_id,
                subgoal_version=agent_subgoal.subgoal_version,
                execution_id=proposal.proposal_id,
            ),
            capabilities=RuntimeCapabilityInventory(
                local_tools=(),
                mcp_connectors=(),
                a2a_agents=(A2AAgentInventoryItem(
                    agent_id="gpt_researcher",
                    semantic_domains=("external_research",),
                    resource_types=("report",),
                    operations=("gpt_researcher",),
                    implementation_present=True,
                    configuration_state="enabled",
                    discovery_state="registered_profile",
                    max_runtime_seconds=240,
                ),),
            ),
        )

    assert rejected.value.feedback.reason == expected_reason
    assert expected_maximum in rejected.value.feedback.required_repair
    assert rejected.value.feedback.repairable_fields == ("operation",)


def test_execution_output_schema_uses_registered_agent_runtime_limit() -> None:
    project, _ = _project_with_frozen_execution()
    subgoal = _subgoal("external-research", "Research the formal release source.")
    subgoal = subgoal.model_copy(update={
        "capability_contract": CapabilityContract(
            contract_id="contract:gpt-researcher",
            operation="gpt_researcher",
            semantic_domain="external_research",
            resource_type="report",
            allowed_execution_kinds=("agent",),
        ),
    })
    inventory = RuntimeCapabilityInventory(
        local_tools=(),
        mcp_connectors=(),
        a2a_agents=(A2AAgentInventoryItem(
            agent_id="gpt_researcher",
            semantic_domains=("external_research",),
            resource_types=("report",),
            operations=("gpt_researcher",),
            implementation_present=True,
            configuration_state="enabled",
            discovery_state="registered_profile",
            max_runtime_seconds=240,
        ),),
    )
    output_type = _execution_output_type(project, inventory, subgoal)
    payload = {
        "operation": {
            "kind": "agent",
            "agent_id": "gpt_researcher",
            "expected_artifact_types": ["report"],
            "token_budget": 4_000,
            "cost_budget": 1.0,
            "time_budget_seconds": 240,
        },
    }

    accepted = output_type.model_validate(payload)

    assert "bounded_sub_goal" not in json.dumps(output_type.model_json_schema())
    assert accepted.operation.time_budget_seconds == 240
    payload["operation"]["time_budget_seconds"] = 241
    with pytest.raises(ValueError, match="less than or equal to 240"):
        output_type.model_validate(payload)

    payload["operation"]["time_budget_seconds"] = 240
    payload["operation"]["token_budget"] = 20_001
    with pytest.raises(ValueError, match="less than or equal to 20000"):
        output_type.model_validate(payload)

    payload["operation"]["token_budget"] = 4_000
    payload["operation"]["cost_budget"] = 20.01
    with pytest.raises(ValueError, match="less than or equal to 20"):
        output_type.model_validate(payload)


def test_execution_output_schema_constrains_tool_to_matched_capability() -> None:
    project, _ = _project_with_frozen_execution()
    subgoal = _subgoal("capture-release", "Read the formal release page.")
    subgoal = subgoal.model_copy(update={
        "capability_contract": CapabilityContract(
            contract_id="capture_url",
            operation="capture_url",
            semantic_domain="web",
            resource_type="web_page",
            allowed_execution_kinds=("tool",),
        ),
    })
    inventory = RuntimeCapabilityInventory(
        local_tools=(
            LocalToolInventoryItem(
                tool_name="capture_url",
                semantic_domains=("web",),
                resource_types=("web_page",),
                operations=("capture_url",),
                exposure="workflow_activity",
                risk_level="low",
                input_schema={"type": "object"},
                provider_availability="not_observed",
            ),
            LocalToolInventoryItem(
                tool_name="web_search",
                semantic_domains=("web",),
                resource_types=("web_page",),
                operations=("web_search",),
                exposure="public_agent",
                risk_level="low",
                input_schema={"type": "object"},
                provider_availability="not_observed",
            ),
        ),
        mcp_connectors=(),
        a2a_agents=(),
    )
    output_type = _execution_output_type(project, inventory, subgoal)
    operation_schema = output_type.model_json_schema()["$defs"][
        "_ToolOperationWithAdmittedCapability"
    ]

    assert operation_schema["properties"]["tool_name"]["const"] == "capture_url"
    with pytest.raises(ValueError, match="capture_url"):
        output_type.model_validate({
            "operation": {
                "kind": "tool",
                "tool_name": "web_search",
                "typed_arguments": {"query": "formal release notes"},
                "expected_artifact_type": "web_page",
            },
        })


def test_web_search_output_rejects_exact_previously_failed_query() -> None:
    project, _ = _project_with_frozen_execution()
    subgoal = _subgoal("search-release", "Search the formal release page.")
    inventory = RuntimeCapabilityInventory(
        local_tools=(
            LocalToolInventoryItem(
                tool_name="web_search",
                semantic_domains=("investigation",),
                resource_types=("evidence",),
                operations=("web_search",),
                exposure="public_agent",
                risk_level="low",
                input_schema={"type": "object"},
                provider_availability="not_observed",
            ),
        ),
        mcp_connectors=(),
        a2a_agents=(),
    )
    old_query = "formal release notes"
    output_type = _execution_output_type(
        project,
        inventory,
        subgoal,
        excluded_tool_operations=(
            ToolExecutionOperation(
                tool_name="web_search",
                typed_arguments={
                    "query": old_query,
                    "limit": 10,
                    "scrape": True,
                },
                expected_artifact_type="web_page",
            ),
        ),
    )

    with pytest.raises(ValueError, match="exactly repeats"):
        output_type.model_validate({
            "operation": {
                "kind": "tool",
                "tool_name": "web_search",
                "typed_arguments": {
                    "query": old_query,
                    "limit": 10,
                    "scrape": True,
                },
                "expected_artifact_type": "web_page",
            },
        })
    output_type.model_validate({
        "operation": {
            "kind": "tool",
            "tool_name": "web_search",
            "typed_arguments": {
                "query": f"{old_query} site:example.test",
                "limit": 10,
                "scrape": True,
            },
            "expected_artifact_type": "web_page",
        },
    })


def test_capture_url_schema_constrains_locator_to_observed_execution_facts() -> None:
    project, _ = _project_with_frozen_execution()
    reference = EvidenceRef(
        evidence_id="evidence-search",
        execution_ref=ExecutionRef(
            execution_id="execution-search",
            execution_kind="tool",
            owner_ref="proposal-search",
            execution_digest="e" * 64,
        ),
        source="tool:web_search",
        content_digest="c" * 64,
    )
    material = (
        EvidenceMaterial(
            reference=reference,
            content=json.dumps({
                "data": {
                    "results": [{
                        "title": "Official releases",
                        "url": "https://github.com/example/protocol/releases",
                    }],
                },
            }),
        ),
    )
    observed = observed_url_locators(project, material)
    subgoal = _subgoal("capture-release", "Read the formal release page.")
    subgoal = subgoal.model_copy(update={
        "capability_contract": CapabilityContract(
            contract_id="capture_url",
            operation="capture_url",
            semantic_domain="web",
            resource_type="web_page",
            allowed_execution_kinds=("tool",),
        ),
    })
    inventory = RuntimeCapabilityInventory(
        local_tools=(LocalToolInventoryItem(
            tool_name="capture_url",
            semantic_domains=("web",),
            resource_types=("web_page",),
            operations=("capture_url",),
            exposure="workflow_activity",
            risk_level="low",
            input_schema={"type": "object"},
            provider_availability="not_observed",
        ),),
        mcp_connectors=(),
        a2a_agents=(),
    )
    output_type = _execution_output_type(
        project,
        inventory,
        subgoal,
        observed_url_locators=observed,
    )

    output_type.model_validate({
        "operation": {
            "kind": "tool",
            "tool_name": "capture_url",
            "typed_arguments": {
                "candidate_id": "url_candidate_01",
            },
            "expected_artifact_type": "web_page",
        },
    })
    with pytest.raises(ValueError, match="Input should be"):
        output_type.model_validate({
            "operation": {
                "kind": "tool",
                "tool_name": "capture_url",
                "typed_arguments": {
                    "candidate_id": "url_candidate_02",
                },
                "expected_artifact_type": "web_page",
            },
        })


def test_investigation_web_search_schema_requires_full_candidate_budget() -> None:
    project, _ = _project_with_frozen_execution()
    subgoal = _subgoal("search-release", "Search formal release evidence.")
    inventory = RuntimeCapabilityInventory(
        local_tools=(LocalToolInventoryItem(
            tool_name="web_search",
            semantic_domains=("investigation",),
            resource_types=("evidence",),
            operations=("web_search",),
            exposure="public_agent",
            risk_level="low",
            input_schema={"type": "object"},
            provider_availability="not_observed",
        ),),
        mcp_connectors=(),
        a2a_agents=(),
    )
    output_type = _execution_output_type(project, inventory, subgoal)

    accepted = output_type.model_validate({
        "operation": {
            "kind": "tool",
            "tool_name": "web_search",
            "typed_arguments": {
                "query": "official protocol releases",
                "limit": 10,
                "scrape": True,
            },
            "expected_artifact_type": "web_page",
        },
    })
    assert accepted.operation.typed_arguments.limit == 10
    with pytest.raises(ValueError, match="Input should be 10"):
        output_type.model_validate({
            "operation": {
                "kind": "tool",
                "tool_name": "web_search",
                "typed_arguments": {
                    "query": "official protocol releases",
                    "limit": 5,
                    "scrape": True,
                },
                "expected_artifact_type": "web_page",
            },
        })


def test_planner_inventory_exposes_capability_classes_without_execution_schema() -> None:
    web_search = LocalToolInventoryItem(
        tool_name="web_search",
        description="Search public web pages.",
        semantic_domains=("web", "docs"),
        resource_types=("web_page",),
        operations=("search", "read"),
        authorization_scope="network:read",
        exposure="public_agent",
        risk_level="low",
        input_schema={
            "type": "object",
            "properties": {
                f"large_{index}": {"type": "string"}
                for index in range(100)
            },
        },
        provider_availability="not_observed",
    )
    interaction_verifier = web_search.model_copy(update={
        "tool_name": "verify_interaction_draft",
        "authorization_scope": "interaction:verify",
    })

    payload = _inventory_payload(RuntimeCapabilityInventory(
        local_tools=(web_search, interaction_verifier),
        mcp_connectors=(),
        a2a_agents=(),
    ))

    assert payload["local_capability_classes"] == [{
        "class_ref": "tool:web_search",
        "description": "Search public web pages.",
        "identity_operation": "web_search",
        "semantic_domains": ("web", "docs"),
        "resource_types": ("web_page",),
        "operations": ("search", "read", "web_search"),
        "allowed_execution_kinds": ("tool",),
    }]
    assert "input_schema" not in str(payload)
    assert {
        item["class_ref"]
        for item in payload["application_capability_classes"]
    } == {"application:synthesis", "application:user_input"}


def test_execution_context_uses_exact_accepted_capability_identity() -> None:
    web_search = LocalToolInventoryItem(
        tool_name="web_search",
        exposure="public_agent",
        risk_level="low",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        provider_availability="not_observed",
    )
    unrelated = LocalToolInventoryItem(
        tool_name="unrelated_large_tool",
        exposure="public_agent",
        risk_level="low",
        input_schema={
            "type": "object",
            "properties": {
                f"field_{index}": {"type": "string"} for index in range(100)
            },
        },
        provider_availability="not_observed",
    )

    payload = _execution_inventory_payload(
        RuntimeCapabilityInventory(
            local_tools=(web_search, unrelated),
            mcp_connectors=(),
            a2a_agents=(),
        ),
        _subgoal("search", "Search the formal source."),
    )

    assert [item["tool_name"] for item in payload["local_tools"]] == ["web_search"]


def test_execution_context_compacts_non_matching_tool_schemas() -> None:
    tool = LocalToolInventoryItem(
        tool_name="web_search",
        semantic_domains=("investigation",),
        resource_types=("evidence",),
        operations=("research",),
        exposure="public_agent",
        risk_level="low",
        input_schema={
            "title": "Presentation-only schema title",
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {
                    "title": "Query",
                    "type": "string",
                    "description": "q" * 400,
                    "default": "",
                    "minLength": 1,
                },
            },
        },
        provider_availability="not_observed",
    )
    semantic_contract = _subgoal("research", "Research the formal source.").model_copy(
        update={
            "capability_contract": CapabilityContract(
                contract_id="contract:research",
                operation="research",
                semantic_domain="investigation",
                resource_type="evidence",
                allowed_execution_kinds=("tool",),
            )
        }
    )

    payload = _execution_inventory_payload(
        RuntimeCapabilityInventory(
            local_tools=(tool,),
            mcp_connectors=(),
            a2a_agents=(),
        ),
        semantic_contract,
    )

    schema = payload["local_tools"][0]["input_schema"]
    assert schema["type"] == "object"
    assert schema["required"] == ["query"]
    assert schema["properties"]["query"]["minLength"] == 1
    assert len(schema["properties"]["query"]["description"]) == 240
    assert "title" not in schema
    assert "default" not in schema["properties"]["query"]


def test_execution_context_excludes_interaction_scoped_verifier_tool() -> None:
    interaction_verifier = LocalToolInventoryItem(
        tool_name="verify_interaction_draft",
        description="Verify a caller-supplied conversation draft.",
        semantic_domains=("verification",),
        resource_types=("draft", "evidence"),
        operations=("verify",),
        authorization_scope="interaction:verify",
        exposure="public_agent",
        risk_level="low",
        input_schema={"type": "object"},
        provider_availability="not_applicable",
    )
    report_validation = _subgoal(
        "validate-report",
        "Validate protocol source relevance.",
    ).model_copy(update={
        "capability_contract": CapabilityContract(
            contract_id="contract:validate-report",
            operation="verify_interaction_draft",
            semantic_domain="verification",
            resource_type="draft",
            allowed_execution_kinds=("tool",),
        ),
    })

    payload = _execution_inventory_payload(
        RuntimeCapabilityInventory(
            local_tools=(interaction_verifier,),
            mcp_connectors=(),
            a2a_agents=(),
        ),
        report_validation,
    )

    assert payload["local_tools"] == []


def test_revision_compiles_version_and_supersede_deterministically() -> None:
    previous = _subgoal("report", "Create the old report.")
    draft = _PlanRevisionDraft.model_validate({
        "derived_requirements": [{
            "requirement_id": "dr-report",
            "statement": "The report is required.",
            "acceptance_contract": "A report is present.",
            "mapped_logical_subgoal_ids": ["report"],
        }],
        "revisable_subgoals": [{
            "logical_subgoal_id": "report",
            "objective": "Create the corrected report.",
            "required_output": "Corrected report",
            "capability_contract": {
                "contract_id": "contract:report",
                "operation": "synthesize",
                "semantic_domain": "report",
                "resource_type": "report",
                "allowed_execution_kinds": ["synthesis"],
            },
        }],
        "requirement_mappings": [{
            "requirement_id": "release-change",
            "logical_subgoal_ids": ["report"],
        }],
    })

    proposal = StructuredInvestigationPlanner._materialize_revision(
        draft,
        project_id="project-1",
        based_on_event_sequence=8,
        capability_revision="capability-v1",
        revision_reason="repair-1",
        frozen_subgoals=(),
        previous_subgoals=(previous,),
        previous_requirement_mappings=(
            RequirementMapping(
                requirement_id="release-change",
                logical_subgoal_ids=("report",),
            ),
            RequirementMapping(
                requirement_id="dr-report",
                logical_subgoal_ids=("old-report",),
            ),
        ),
        previous_derived_requirement_ids=("dr-report",),
        frozen_gap_ids=(),
    )

    revised = proposal.subgoals[0]
    assert revised.subgoal_version == 2
    assert revised.supersedes_version == 1
    assert revised.definition_digest != previous.definition_digest
    assert proposal.requirement_mappings == (
        RequirementMapping(
            requirement_id="release-change",
            logical_subgoal_ids=("report",),
        ),
        RequirementMapping(
            requirement_id="dr-report",
            logical_subgoal_ids=("report",),
        ),
    )


def test_derived_requirement_draft_cannot_omit_coverage_mapping() -> None:
    payload = {
        "derived_requirements": [{
            "requirement_id": "verify-exclusions",
            "statement": "Verify source exclusions.",
            "acceptance_contract": "No excluded source is cited.",
        }],
        "subgoals": [{
            "logical_subgoal_id": "report",
            "objective": "Create the report.",
            "required_output": "Report",
            "capability_contract": {
                "contract_id": "contract:report",
                "operation": "synthesize",
                "semantic_domain": "report",
                "resource_type": "report",
                "allowed_execution_kinds": ["synthesis"],
            },
        }],
        "requirement_mappings": [{
            "requirement_id": "release-change",
            "logical_subgoal_ids": ["report"],
        }],
    }
    with pytest.raises(ValueError, match="mapped_logical_subgoal_ids"):
        _PlanDraft.model_validate(payload)

    payload["derived_requirements"][0]["mapped_logical_subgoal_ids"] = ["report"]
    draft = _PlanDraft.model_validate(payload)
    proposal = StructuredInvestigationPlanner._materialize(
        draft,
        project_id="project-1",
        based_on_event_sequence=1,
        capability_revision="capability-v1",
        revision_reason="initial",
    )

    assert proposal.derived_requirements[0].requirement_id == "verify-exclusions"
    assert proposal.requirement_mappings[-1] == RequirementMapping(
        requirement_id="verify-exclusions",
        logical_subgoal_ids=("report",),
    )


def test_plan_draft_rejects_project_verification_as_execution_work() -> None:
    payload = {
        "subgoals": [{
            "logical_subgoal_id": "verify",
            "objective": "Verify exclusions.",
            "required_output": "Verification result",
            "capability_contract": {
                "contract_id": "contract:verify",
                "operation": "verify",
                "semantic_domain": "semantic_verification",
                "resource_type": "evidence",
                "allowed_execution_kinds": ["synthesis"],
            },
        }],
        "requirement_mappings": [{
            "requirement_id": "release-change",
            "logical_subgoal_ids": ["verify"],
        }],
    }

    with pytest.raises(ValueError, match="semantic verification is automatic"):
        _PlanDraft.model_validate(payload)


def test_plan_admission_keeps_semantic_verification_out_of_plan_work() -> None:
    project, _ = _project_with_frozen_execution()
    verifier = _subgoal("verify", "Verify exclusions.").model_copy(update={
        "capability_contract": CapabilityContract(
            contract_id="contract:verify",
            operation="verify",
            semantic_domain="verification",
            resource_type="evidence",
            allowed_execution_kinds=("synthesis",),
        ),
    })
    verifier = verifier.model_copy(
        update={"definition_digest": subgoal_definition_digest(verifier)}
    )
    proposal = PlanProposal(
        project_id=project.definition.project_id,
        based_on_event_sequence=project.event_sequence,
        capability_snapshot_revision="capability-v1",
        revision_reason="invalid-verifier",
        subgoals=(verifier,),
        requirement_mappings=(
            RequirementMapping(
                requirement_id="release-change",
                logical_subgoal_ids=("verify",),
            ),
        ),
    )

    with pytest.raises(ProposalRejected, match="automatic Verifier"):
        PlanAdmission().accept(
            project,
            proposal,
            capabilities=RuntimeCapabilityInventory(
                local_tools=(),
                mcp_connectors=(),
                a2a_agents=(),
            ),
        )


def test_plan_admission_keeps_user_and_derived_requirement_ids_disjoint() -> None:
    project, frozen = _project_with_frozen_execution()
    proposal = project.accepted_plan.proposal.model_copy(update={
        "based_on_event_sequence": project.event_sequence,
        "derived_requirements": (
            DerivedRequirement(
                requirement_id="release-change",
                statement="Shadow the user requirement.",
                acceptance_contract="Must never be admitted.",
            ),
        ),
        "subgoals": (frozen,),
    })

    with pytest.raises(ProposalRejected, match="cannot reuse user requirement ids"):
        PlanAdmission().accept(
            project,
            proposal,
            capabilities=RuntimeCapabilityInventory(
                local_tools=(
                    LocalToolInventoryItem(
                        tool_name="web_search",
                        exposure="public_agent",
                        risk_level="low",
                        input_schema={"type": "object"},
                        provider_availability="not_observed",
                    ),
                ),
                mcp_connectors=(),
                a2a_agents=(),
            ),
        )
