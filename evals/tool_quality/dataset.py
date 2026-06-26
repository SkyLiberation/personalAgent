"""Dataset model + loader for tool governance quality cases."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolEvalCase:
    id: str
    description: str
    business_scenario: str
    tool_name: str
    expected_exposure: str | None = None
    expected_risk_level: str | None = None
    expected_requires_confirmation: bool | None = None
    expected_side_effects: list[str] | None = None
    expected_permission_scope: str | None = None
    expected_idempotency_key_required: bool | None = None
    expected_audit_required: bool | None = None
    expected_timeout_seconds: float | None = None
    expected_max_retries: int | None = None
    expected_rate_limit_per_minute: int | None = None


@dataclass(frozen=True)
class ToolRunOutput:
    """Scoreable projection of one registered tool."""

    tool_name: str
    exposure: str
    risk_level: str
    requires_confirmation: bool
    side_effects: list[str] = field(default_factory=list)
    permission_scope: str = ""
    idempotency_key_required: bool = False
    audit_required: bool = True
    timeout_seconds: float | None = None
    max_retries: int = 0
    rate_limit_per_minute: int | None = None


@dataclass(frozen=True)
class ToolExecutionEvalCase:
    id: str
    description: str
    tool_name: str
    args: dict[str, object] = field(default_factory=dict)
    repeat_same_call: bool = False
    expected_ok: bool = True
    expected_error_kind: str | None = None
    expected_data_keys: list[str] = field(default_factory=list)
    expected_evidence_min_count: int = 0
    expected_repeat_ok: bool | None = None
    expected_repeat_error_kind: str | None = None
    expected_call_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolExecutionRunOutput:
    tool_name: str
    ok: bool
    error_kind: str | None = None
    data_keys: list[str] = field(default_factory=list)
    evidence_count: int = 0
    repeat_ok: bool | None = None
    repeat_error_kind: str | None = None
    call_counts: dict[str, int] = field(default_factory=dict)


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def load_cases(path: str | Path) -> list[ToolEvalCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        ToolEvalCase(
            id=str(item["id"]),
            description=str(item.get("description", "")),
            business_scenario=str(item.get("business_scenario", "")),
            tool_name=str(item["tool_name"]),
            expected_exposure=item.get("expected_exposure"),
            expected_risk_level=item.get("expected_risk_level"),
            expected_requires_confirmation=item.get("expected_requires_confirmation"),
            expected_side_effects=(
                [str(effect) for effect in item["expected_side_effects"]]
                if "expected_side_effects" in item else None
            ),
            expected_permission_scope=item.get("expected_permission_scope"),
            expected_idempotency_key_required=item.get("expected_idempotency_key_required"),
            expected_audit_required=item.get("expected_audit_required"),
            expected_timeout_seconds=_optional_float(item.get("expected_timeout_seconds")),
            expected_max_retries=_optional_int(item.get("expected_max_retries")),
            expected_rate_limit_per_minute=_optional_int(item.get("expected_rate_limit_per_minute")),
        )
        for item in raw
    ]


def load_execution_cases(path: str | Path) -> list[ToolExecutionEvalCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        ToolExecutionEvalCase(
            id=str(item["id"]),
            description=str(item.get("description", "")),
            tool_name=str(item["tool_name"]),
            args=dict(item.get("args") or {}),
            repeat_same_call=bool(item.get("repeat_same_call", False)),
            expected_ok=bool(item.get("expected_ok", True)),
            expected_error_kind=item.get("expected_error_kind"),
            expected_data_keys=[str(key) for key in item.get("expected_data_keys", [])],
            expected_evidence_min_count=int(item.get("expected_evidence_min_count", 0)),
            expected_repeat_ok=item.get("expected_repeat_ok"),
            expected_repeat_error_kind=item.get("expected_repeat_error_kind"),
            expected_call_counts={
                str(key): int(value)
                for key, value in (item.get("expected_call_counts") or {}).items()
            },
        )
        for item in raw
    ]


def default_cases_path() -> Path:
    return Path(__file__).parent / "cases.json"


def default_execution_cases_path() -> Path:
    return Path(__file__).parent / "execution_cases.json"
