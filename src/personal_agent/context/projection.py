"""Purpose-scoped context projection with explicit budgets and snapshots."""

from __future__ import annotations

import json

from personal_agent.kernel.contracts.agentic import (
    ContextBudget,
    ContextItem,
    ContextProjection,
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


class ContextManager:
    def project(
        self,
        items: tuple[ContextItem, ...],
        *,
        purpose: str,
        budget: ContextBudget,
        ledger_revision: int,
        event_cursor: str,
        artifact_versions: dict[str, str] | None = None,
    ) -> ContextProjection:
        usable = (
            budget.max_context_tokens
            - budget.safety_margin
            - budget.reserved_output_tokens
        )
        if usable <= 0:
            raise ContextBudgetError("context budget has no usable input capacity")
        ordered = sorted(
            items,
            key=lambda item: (
                _AUTHORITY.get(str(item.payload.get("authority_tier", "generated_candidate")), 9),
                item.ref_id,
            ),
        )
        selected: list[str] = []
        omitted: list[str] = []
        reasons: dict[str, str] = {}
        consumed = 0
        for item in ordered:
            serialized = item.summary + json.dumps(
                item.payload, ensure_ascii=False, sort_keys=True, default=str,
            )
            estimate = max(1, len(serialized) // 4)
            if consumed + estimate <= usable:
                selected.append(item.ref_id)
                consumed += estimate
                reasons[item.ref_id] = f"selected_for:{purpose}"
            else:
                omitted.append(item.ref_id)
        return ContextProjection(
            purpose=purpose,
            item_refs=tuple(selected),
            omitted_refs=tuple(omitted),
            token_estimate=consumed,
            selection_reasons=reasons,
            ledger_revision=ledger_revision,
            event_cursor=event_cursor,
            artifact_versions=artifact_versions or {},
            model_profile=budget.model_profile,
            tokenizer_profile=budget.tokenizer_profile,
        )


__all__ = ["ContextBudgetError", "ContextManager"]
