"""Resolve model proposals against authoritative access declarations."""

from __future__ import annotations

from personal_agent.runtime.contracts.control import (
    ProposedResourceAccessPlan,
    ResolvedResourceAccessPlan,
)


class ResourceAccessResolutionError(ValueError):
    """An authoritative declaration conflicts with the accepted action scope."""


class ResourceAccessResolver:
    """Validate authoritative declarations without rewriting the accepted scope."""

    def resolve(
        self,
        proposed: ProposedResourceAccessPlan,
        *,
        procedure_contract: ProposedResourceAccessPlan | None = None,
        capability_manifest: ProposedResourceAccessPlan | None = None,
        tool_schema: ProposedResourceAccessPlan | None = None,
        runtime_preflight: ProposedResourceAccessPlan | None = None,
        preflight_complete: bool = True,
    ) -> ResolvedResourceAccessPlan:
        ordered = (
            ("procedure_contract", procedure_contract),
            ("capability_manifest", capability_manifest),
            ("tool_schema", tool_schema),
            ("runtime_preflight", runtime_preflight),
            ("model_proposal", proposed),
        )
        source_refs: list[str] = []
        for source, plan in ordered:
            if plan is None:
                continue
            source_refs.append(source)
            if source != "model_proposal":
                _validate_no_scope_rewrite(proposed, plan, source=source)
        complete = preflight_complete and not (
            proposed.side_effect_class != "none"
            and runtime_preflight is None and tool_schema is None
            and capability_manifest is None and procedure_contract is None
        )
        return ResolvedResourceAccessPlan(
            **proposed.model_dump(mode="python"),
            source_refs=tuple(source_refs),
            resolution_evidence=tuple(
                f"{source}:declared" for source in source_refs
            ),
            complete=complete,
        )


def _validate_no_scope_rewrite(
    proposed: ProposedResourceAccessPlan,
    authoritative: ProposedResourceAccessPlan,
    *,
    source: str,
) -> None:
    proposed_reads = {(item.semantic_domain, item.locator) for item in proposed.read_set}
    proposed_writes = {(item.semantic_domain, item.locator) for item in proposed.write_set}
    authoritative_reads = {
        (item.semantic_domain, item.locator) for item in authoritative.read_set
    }
    authoritative_writes = {
        (item.semantic_domain, item.locator) for item in authoritative.write_set
    }
    if not authoritative_reads.issubset(proposed_reads):
        raise ResourceAccessResolutionError(f"{source} requires undeclared read access")
    if not authoritative_writes.issubset(proposed_writes):
        raise ResourceAccessResolutionError(f"{source} requires undeclared write access")
    boundary_fields = (
        "side_effect_class",
        "authority_scope",
        "data_egress_class",
        "trust_floor",
        "freshness_contract",
        "evidence_contract",
        "failure_semantics",
    )
    conflicts = tuple(
        field for field in boundary_fields
        if getattr(authoritative, field) != getattr(proposed, field)
    )
    if conflicts:
        raise ResourceAccessResolutionError(
            f"{source} conflicts with proposed boundaries: {','.join(conflicts)}"
        )


__all__ = ["ResourceAccessResolutionError", "ResourceAccessResolver"]
