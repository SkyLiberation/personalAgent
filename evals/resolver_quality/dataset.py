from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResolverQualityCase:
    id: str
    task_text: str
    workflow_scope: str
    expected_capability_ids: tuple[str, ...] = ()
    forbidden_capability_ids: tuple[str, ...] = ()
    expected_denial_reasons: tuple[str, ...] = ()
    min_selected: int = 0
    max_selected: int | None = None


def load_cases(path: Path | None = None) -> tuple[ResolverQualityCase, ...]:
    source = path or Path(__file__).with_name("cases.json")
    raw = json.loads(source.read_text(encoding="utf-8"))
    return tuple(
        ResolverQualityCase(
            id=str(item["id"]),
            task_text=str(item["task_text"]),
            workflow_scope=str(item["workflow_scope"]),
            expected_capability_ids=tuple(str(value) for value in item.get("expected_capability_ids", ())),
            forbidden_capability_ids=tuple(str(value) for value in item.get("forbidden_capability_ids", ())),
            expected_denial_reasons=tuple(str(value) for value in item.get("expected_denial_reasons", ())),
            min_selected=int(item.get("min_selected", 0)),
            max_selected=(
                int(item["max_selected"])
                if item.get("max_selected") is not None
                else None
            ),
        )
        for item in raw
    )


__all__ = ["ResolverQualityCase", "load_cases"]
