"""Materialize purpose-scoped model context from an audited projection."""

from __future__ import annotations

from collections import Counter
from pydantic import BaseModel, ConfigDict

from personal_agent.kernel.contracts.agentic import ContextItem, ContextProjection


class ContextMaterializationError(ValueError):
    pass


class MaterializedModelContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projection_id: str
    purpose: str
    instruction_items: tuple[ContextItem, ...] = ()
    content_items: tuple[ContextItem, ...] = ()

    @property
    def materialized_refs(self) -> tuple[str, ...]:
        return tuple(item.ref_id for item in (*self.instruction_items, *self.content_items))

    def model_payload(self) -> dict[str, object]:
        return {
            "projection_id": self.projection_id,
            "purpose": self.purpose,
            "trusted_context": [
                item.model_dump(mode="json") for item in self.instruction_items
            ],
            "untrusted_content": [
                item.model_dump(mode="json") for item in self.content_items
            ],
        }


class ContextProjectionMaterializer:
    """Specification that turns projection refs into the only visible items."""

    def materialize(
        self,
        projection: ContextProjection,
        items: tuple[ContextItem, ...],
    ) -> MaterializedModelContext:
        by_ref = {item.ref_id: item for item in items}
        if len(by_ref) != len(items):
            duplicates = sorted(
                ref for ref, count in Counter(item.ref_id for item in items).items()
                if count > 1
            )
            raise ContextMaterializationError(
                "context item refs must be unique: " + ", ".join(duplicates)
            )
        selected = set(projection.item_refs)
        forbidden = set(projection.omitted_refs).union(projection.redacted_refs)
        if selected.intersection(forbidden):
            raise ContextMaterializationError("projection selects an omitted or redacted item")
        missing = selected - set(by_ref)
        if missing:
            raise ContextMaterializationError(
                "projection references missing context items: " + ", ".join(sorted(missing))
            )
        ordered = tuple(by_ref[ref] for ref in projection.item_refs)
        instruction_items = tuple(
            item for item in ordered
            if item.trust_tier in {"runtime", "trusted"} and item.admitted
        )
        content_items = tuple(item for item in ordered if item not in instruction_items)
        return MaterializedModelContext(
            projection_id=projection.projection_id,
            purpose=projection.purpose,
            instruction_items=instruction_items,
            content_items=content_items,
        )


class ModelContextGateway:
    """Single model-context boundary; callers cannot bypass projection refs."""

    def __init__(self, materializer: ContextProjectionMaterializer | None = None) -> None:
        self._materializer = materializer or ContextProjectionMaterializer()

    def open(
        self,
        projection: ContextProjection,
        items: tuple[ContextItem, ...],
        *,
        purpose: str,
    ) -> MaterializedModelContext:
        if projection.purpose != purpose:
            raise ContextMaterializationError("context projection purpose mismatch")
        return self._materializer.materialize(projection, items)


__all__ = [
    "ContextMaterializationError",
    "ContextProjectionMaterializer",
    "MaterializedModelContext",
    "ModelContextGateway",
]
