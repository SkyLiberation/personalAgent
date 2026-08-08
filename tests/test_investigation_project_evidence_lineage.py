from __future__ import annotations

import json

import pytest

from personal_agent.application.investigation_project.model_ports import (
    _evidence_material_payload,
    _final_generated_content_output_type,
    _generated_content_output_type,
    _repair_candidate_context,
)
from personal_agent.application.investigation_project.ports import EvidenceMaterial
from personal_agent.application.investigation_project.service import (
    InvestigationProjectService,
    _web_search_evidence_context,
)
from personal_agent.domain.investigation_project import (
    AcceptedPlanVersion,
    CapabilityContract,
    EvidenceRef,
    ExecutionRef,
    InvestigationProject,
    InvestigationProjectDefinition,
    PlanProposal,
    RequirementMapping,
    SubGoalDefinitionVersion,
    SubGoalVersionRef,
    UserRequirement,
    UserRequirementVersion,
    WaitingReason,
)
from personal_agent.kernel.contracts.scope import (
    AuthenticatedPrincipal,
)


def _project() -> InvestigationProject:
    requirement = UserRequirement(
        requirement_id="formal-source",
        statement="Use a formal source.",
        acceptance_contract="The source must not be derived synthesis.",
    )
    return InvestigationProject(
        definition=InvestigationProjectDefinition(
            project_id="project-1",
            principal=AuthenticatedPrincipal(
                tenant_id="tenant-1",
                user_id="user-1",
            ),
            title="Source investigation",
            goal="Use formal sources.",
            user_requirements=UserRequirementVersion(
                version=1,
                requirements=(requirement,),
            ),
            create_idempotency_key="create-1",
        )
    )


def _evidence(evidence_id: str, source: str) -> EvidenceRef:
    return EvidenceRef(
        evidence_id=evidence_id,
        execution_ref=ExecutionRef(
            execution_id=f"execution:{evidence_id}",
            execution_kind="synthesis" if source == "synthesis" else "tool",
            owner_ref=f"owner:{evidence_id}",
            execution_digest="e" * 64,
        ),
        source=source,
        content_digest="c" * 64,
        summary=f"{source} evidence",
    )


def _subgoal(
    logical_subgoal_id: str,
    *,
    repairs: tuple[SubGoalVersionRef, ...] = (),
) -> SubGoalDefinitionVersion:
    return SubGoalDefinitionVersion(
        logical_subgoal_id=logical_subgoal_id,
        subgoal_version=1,
        definition_digest=logical_subgoal_id.ljust(64, "0"),
        objective=f"Investigate {logical_subgoal_id}.",
        required_output=f"{logical_subgoal_id} evidence",
        capability_contract=CapabilityContract(
            contract_id=f"contract:{logical_subgoal_id}",
            operation="web_search",
            semantic_domain="investigation",
            resource_type="evidence",
            allowed_execution_kinds=("tool",),
        ),
        repairs_frozen_subgoals=repairs,
    )


def test_execution_evidence_is_scoped_to_repair_lineage() -> None:
    project = _project()
    mcp = _subgoal("mcp-search")
    a2a = _subgoal("a2a-search")
    a2a_repair = _subgoal(
        "a2a-official-source",
        repairs=(
            SubGoalVersionRef(
                logical_subgoal_id=a2a.logical_subgoal_id,
                subgoal_version=a2a.subgoal_version,
            ),
        ),
    )
    a2a_capture_repair = _subgoal(
        "a2a-official-page",
        repairs=(
            SubGoalVersionRef(
                logical_subgoal_id=a2a_repair.logical_subgoal_id,
                subgoal_version=a2a_repair.subgoal_version,
            ),
        ),
    )
    project.accepted_plan = AcceptedPlanVersion(
        plan_version=2,
        proposal=PlanProposal(
            project_id=project.definition.project_id,
            based_on_event_sequence=1,
            capability_snapshot_revision="capability-v1",
            revision_reason="repair A2A evidence",
            subgoals=(mcp, a2a, a2a_repair, a2a_capture_repair),
            requirement_mappings=(
                RequirementMapping(
                    requirement_id="formal-source",
                    logical_subgoal_ids=(a2a_repair.logical_subgoal_id,),
                ),
            ),
        ),
        plan_digest="p" * 64,
    )
    mcp_evidence = _evidence("mcp-evidence", "tool:web_search")
    a2a_evidence = _evidence("a2a-evidence", "tool:web_search")
    a2a_repair_evidence = _evidence(
        "a2a-repair-evidence",
        "tool:capture_url",
    )
    project.execution_refs[(mcp.logical_subgoal_id, 1)] = (
        mcp_evidence.execution_ref
    )
    project.execution_refs[(a2a.logical_subgoal_id, 1)] = (
        a2a_evidence.execution_ref
    )
    project.execution_refs[(a2a_repair.logical_subgoal_id, 1)] = (
        a2a_repair_evidence.execution_ref
    )
    project.admitted_evidence[mcp_evidence.evidence_id] = mcp_evidence
    project.admitted_evidence[a2a_evidence.evidence_id] = a2a_evidence
    project.admitted_evidence[
        a2a_repair_evidence.evidence_id
    ] = a2a_repair_evidence

    scoped = InvestigationProjectService._execution_evidence_refs(
        project,
        a2a_repair,
    )

    assert tuple(item.evidence_id for item in scoped) == ("a2a-evidence",)

    recursively_scoped = InvestigationProjectService._execution_evidence_refs(
        project,
        a2a_capture_repair,
    )

    assert tuple(item.evidence_id for item in recursively_scoped) == (
        "a2a-evidence",
        "a2a-repair-evidence",
    )

    grouped = _repair_candidate_context(
        project,
        (
            WaitingReason(
                logical_subgoal_id=mcp.logical_subgoal_id,
                subgoal_version=mcp.subgoal_version,
                reason="verification_repair",
                recovery_authority="planner",
            ),
            WaitingReason(
                logical_subgoal_id=a2a.logical_subgoal_id,
                subgoal_version=a2a.subgoal_version,
                reason="verification_repair",
                recovery_authority="planner",
            ),
        ),
        (
            EvidenceMaterial(reference=mcp_evidence, content="MCP candidates"),
            EvidenceMaterial(reference=a2a_evidence, content="A2A candidates"),
        ),
    )

    assert [
        item["candidate_evidence"][0]["project_evidence_id"]
        for item in grouped
    ] == ["mcp-evidence", "a2a-evidence"]


def test_generated_content_requires_direct_admitted_source_evidence() -> None:
    project = _project()
    direct = _evidence("direct-1", "tool:web_search")
    derived = _evidence("derived-1", "synthesis")
    project.admitted_evidence[direct.evidence_id] = direct
    project.admitted_evidence[derived.evidence_id] = derived
    service = object.__new__(InvestigationProjectService)

    assert service._referenced_source_evidence(
        project,
        (direct.evidence_id,),
    ) == (direct,)
    with pytest.raises(ValueError, match="unknown evidence"):
        service._referenced_source_evidence(project, ("missing",))
    with pytest.raises(ValueError, match="derived synthesis"):
        service._referenced_source_evidence(project, (derived.evidence_id,))
    with pytest.raises(ValueError, match="requires direct admitted evidence"):
        service._referenced_source_evidence(project, ())


def test_model_evidence_payload_distinguishes_project_id_from_source_locators() -> None:
    direct = _evidence("ipev-direct", "tool:web_search")

    payload = _evidence_material_payload((
        EvidenceMaterial(
            reference=direct,
            content='{"evidence": [{"evidence_ref": "nested-source-hash"}]}',
        ),
    ))

    assert payload[0]["project_evidence_id"] == "ipev-direct"
    assert "reference" not in payload[0]
    assert "nested-source-hash" in payload[0]["content"]


def test_web_search_context_keeps_all_results_without_duplicate_provider_evidence() -> None:
    content = json.dumps({
        "tool": "web_search",
        "data": {
            "results": [
                {
                    "title": "Excluded generic result",
                    "url": "https://blog.example/announcement",
                    "published_at": None,
                    "snippet": "No release date.",
                },
                {
                    "title": "Official releases",
                    "url": "https://github.com/example/protocol/releases",
                    "published_at": None,
                    "snippet": (
                        "v0.2.1 released May 27, 2025; verified on 2025-06-30."
                    ),
                },
            ],
        },
        "evidence": [{"evidence_id": "duplicated-provider-locator"}],
    })

    projected = json.loads(_web_search_evidence_context(content))

    assert len(projected["data"]["results"]) == 2
    official = projected["data"]["results"][1]
    assert official["host"] == "github.com"
    assert official["explicit_dates_in_title_or_snippet"] == [
        "2025-06-30",
        "May 27, 2025",
    ]
    assert "duplicated-provider-locator" not in json.dumps(projected)


def test_generated_content_schema_only_accepts_admitted_direct_evidence_ids() -> None:
    direct = _evidence("ipev-direct", "tool:capture_url")
    output_type = _generated_content_output_type((
        EvidenceMaterial(reference=direct, content="official source"),
    ))

    valid = output_type.model_validate({
        "content": "report",
        "evidence_refs": ["ipev-direct"],
        "limitations": [],
    })

    assert valid.evidence_refs == ("ipev-direct",)
    with pytest.raises(ValueError, match="ipev-direct"):
        output_type.model_validate({
            "content": "report",
            "evidence_refs": ["ipev-direc"],
            "limitations": [],
        })


def test_final_report_schema_requires_explicit_limitations() -> None:
    direct = _evidence("ipev-direct", "tool:capture_url")
    output_type = _final_generated_content_output_type((
        EvidenceMaterial(reference=direct, content="official source"),
    ))

    with pytest.raises(ValueError, match="limitations"):
        output_type.model_validate({
            "content": "report",
            "evidence_refs": ["ipev-direct"],
            "limitations": [],
        })

    result = output_type.model_validate({
        "content": "report",
        "evidence_refs": ["ipev-direct"],
        "limitations": ["The release page does not provide migration data."],
    })
    assert result.limitations
