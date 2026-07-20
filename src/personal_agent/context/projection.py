"""Four-stage context protocol: visibility, retrieval, semantic selection, materialization."""

from __future__ import annotations

import json
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.runtime.contracts.task import (
    ContextBudget,
    ContextItem,
    ContextProjection,
    ProjectionExclusion,
    RuntimeSnapshotRef,
)


_AUTHORITY = {
    "system_policy": 0,
    "user_instruction": 1,
    "trusted_method": 2,
    "generated_candidate": 3,
    "untrusted_content": 4,
}


class ContextBudgetError(ValueError):
    pass


class ContextSelectionRequired(ValueError):
    pass


class ContextRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    purpose: str = Field(min_length=1)
    semantic_query: str = Field(min_length=1)
    required_item_ids: tuple[str, ...] = ()
    allowed_categories: tuple[str, ...] = ()
    allowed_kinds: tuple[str, ...] = ()
    max_candidates: int = Field(default=64, ge=1)
    semantic_selection_required: bool = True


class ContextSelectionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    requirement_ref: str
    source: Literal["model", "contract_derivation"]
    required_item_ids: tuple[str, ...] = ()
    optional_item_ids: tuple[str, ...] = ()
    optional_priority: tuple[str, ...] = ()


class ContextRetrievalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_ref: str
    visible_item_ids: tuple[str, ...]
    candidate_item_ids: tuple[str, ...]
    excluded_item_ids: tuple[str, ...]
    retrieval_rule: Literal["explicit_contract_filter"] = "explicit_contract_filter"
    rule_version: str = "v1"


class ContextManager:
    def project_contract(
        self,
        items: tuple[ContextItem, ...],
        *,
        purpose: str,
        budget: ContextBudget,
        source_snapshot: RuntimeSnapshotRef,
    ) -> ContextProjection:
        """Project an exact upstream-declared set; no hidden relevance ranking occurs."""
        requirement = ContextRequirement(
            purpose=purpose,
            semantic_query=f"materialize exact contract items for {purpose}",
            required_item_ids=tuple(item.item_id for item in items),
            max_candidates=max(len(items), 1),
            semantic_selection_required=False,
        )
        selection = ContextSelectionProposal(
            requirement_ref=requirement.requirement_id,
            source="contract_derivation",
            required_item_ids=requirement.required_item_ids,
        )
        return self.project(
            items,
            requirement=requirement,
            selection=selection,
            budget=budget,
            source_snapshot=source_snapshot,
        )

    def project(
        self,
        items: tuple[ContextItem, ...],
        *,
        requirement: ContextRequirement,
        selection: ContextSelectionProposal | None,
        budget: ContextBudget,
        source_snapshot: RuntimeSnapshotRef,
    ) -> ContextProjection:
        usable = budget.max_context_tokens - budget.safety_margin - budget.reserved_output_tokens
        if usable <= 0:
            raise ContextBudgetError("context budget has no usable input capacity")
        purpose = requirement.purpose
        visible, visibility_omitted = self._visibility_envelope(items, purpose)
        candidates = self._retrieve(visible, requirement)
        candidate_ids = {item.item_id for item in candidates}
        missing_required = set(requirement.required_item_ids) - candidate_ids
        if missing_required:
            raise ContextSelectionRequired(
                f"required context is not visible/retrievable: {sorted(missing_required)}"
            )
        if selection is None:
            raise ContextSelectionRequired("semantic context selection proposal is required")
        if selection.requirement_ref != requirement.requirement_id:
            raise ContextSelectionRequired("selection does not reference the context requirement")
        selected_ids = (*selection.required_item_ids, *selection.optional_item_ids)
        if not set(selected_ids).issubset(candidate_ids):
            raise ContextSelectionRequired("selection references a non-candidate item")
        if not set(requirement.required_item_ids).issubset(selection.required_item_ids):
            raise ContextSelectionRequired("selection omitted contract-required context")
        if requirement.semantic_selection_required and selection.source != "model":
            raise ContextSelectionRequired("open semantic relevance requires a model proposal")
        ordered_ids = tuple(dict.fromkeys((
            *selection.required_item_ids,
            *(selection.optional_priority or selection.optional_item_ids),
        )))
        by_id = {item.item_id: item for item in candidates}
        required = set(selection.required_item_ids)
        selected: list[str] = []
        omitted = list(visibility_omitted)
        reasons: dict[str, str] = {}
        consumed = 0
        for item_id in ordered_ids:
            item = by_id[item_id]
            estimate = _token_estimate(item)
            if consumed + estimate <= usable:
                selected.append(item_id)
                consumed += estimate
                reasons[item_id] = (
                    "required_by_context_contract" if item_id in required
                    else "selected_by_semantic_proposal"
                )
            elif item_id in required:
                raise ContextBudgetError(f"required context exceeds budget: {item_id}")
            else:
                omitted.append(ProjectionExclusion(item_id=item_id, reason="budget"))
        unselected = candidate_ids - set(ordered_ids)
        omitted.extend(
            ProjectionExclusion(item_id=item_id, reason="relevance")
            for item_id in sorted(unselected)
        )
        retrieval = ContextRetrievalRecord(
            requirement_ref=requirement.requirement_id,
            visible_item_ids=tuple(item.item_id for item in visible),
            candidate_item_ids=tuple(item.item_id for item in candidates),
            excluded_item_ids=tuple(item.item_id for item in visibility_omitted),
        )
        return ContextProjection(
            purpose=purpose,
            source_snapshot=source_snapshot,
            selected_item_ids=tuple(selected),
            omitted=tuple(omitted),
            token_estimate=consumed,
            compaction_refs=(f"context-retrieval:{retrieval.requirement_ref}:{retrieval.rule_version}",),
            selection_reasons=reasons,
            projection_policy_version="context-four-stage:v1",
            model_profile=budget.model_profile,
            tokenizer_profile=budget.tokenizer_profile,
        )

    @staticmethod
    def _visibility_envelope(
        items: tuple[ContextItem, ...],
        purpose: str,
    ) -> tuple[tuple[ContextItem, ...], tuple[ProjectionExclusion, ...]]:
        visible: list[ContextItem] = []
        omitted: list[ProjectionExclusion] = []
        for item in items:
            purpose_allowlist = tuple(item.payload.get("purpose_allowlist", ()))
            denied = item.payload.get("visible") is False or (
                purpose_allowlist and purpose not in purpose_allowlist
            )
            if denied:
                omitted.append(ProjectionExclusion(item_id=item.item_id, reason="policy"))
            else:
                visible.append(item)
        return tuple(visible), tuple(omitted)

    @staticmethod
    def _retrieve(
        visible: tuple[ContextItem, ...],
        requirement: ContextRequirement,
    ) -> tuple[ContextItem, ...]:
        allowed_categories = set(requirement.allowed_categories)
        allowed_kinds = set(requirement.allowed_kinds)
        filtered = tuple(
            item for item in visible
            if (not allowed_categories or item.category in allowed_categories)
            and (not allowed_kinds or item.kind in allowed_kinds)
        )
        ordered = sorted(filtered, key=lambda item: (
            0 if item.item_id in requirement.required_item_ids else 1,
            _AUTHORITY.get(str(item.payload.get("authority_tier", "generated_candidate")), 9),
            item.item_id,
        ))
        return tuple(ordered[:requirement.max_candidates])


def _token_estimate(item: ContextItem) -> int:
    serialized = item.summary + json.dumps(
        item.payload, ensure_ascii=False, sort_keys=True, default=str,
    )
    return max(1, len(serialized) // 4)


__all__ = [
    "ContextBudgetError", "ContextManager", "ContextRequirement", "ContextRetrievalRecord",
    "ContextSelectionProposal", "ContextSelectionRequired",
]
