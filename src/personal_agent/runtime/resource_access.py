"""Resolve model proposals against authoritative access declarations."""

from __future__ import annotations

from personal_agent.kernel.contracts.executive import (
    ProposedResourceAccessPlan,
    ResolvedResourceAccessPlan,
    ResourceAccess,
)


class ResourceAccessResolver:
    """Conservative resolver: every declared access is retained, never weakened."""

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
        read_set: list[ResourceAccess] = []
        write_set: list[ResourceAccess] = []
        source_refs: list[str] = []
        side_effect = "none"
        for source, plan in ordered:
            if plan is None:
                continue
            source_refs.append(source)
            _extend_unique(read_set, plan.read_set)
            _extend_unique(write_set, plan.write_set)
            if plan.side_effect_class != "none":
                side_effect = plan.side_effect_class
        complete = preflight_complete and not (
            side_effect != "none" and runtime_preflight is None and tool_schema is None
            and capability_manifest is None and procedure_contract is None
        )
        return ResolvedResourceAccessPlan(
            read_set=tuple(read_set),
            write_set=tuple(write_set),
            side_effect_class=side_effect,
            source_refs=tuple(source_refs),
            resolution_evidence=tuple(
                f"{source}:declared" for source in source_refs
            ),
            complete=complete,
        )


def _extend_unique(target: list[ResourceAccess], values: tuple[ResourceAccess, ...]) -> None:
    seen = {(item.semantic_domain, item.locator) for item in target}
    for value in values:
        key = (value.semantic_domain, value.locator)
        if key not in seen:
            target.append(value)
            seen.add(key)


__all__ = ["ResourceAccessResolver"]
