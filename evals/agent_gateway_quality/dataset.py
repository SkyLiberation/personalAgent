from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentGatewayQualityCase:
    id: str
    operation: str
    agent_id: str
    expected_status: str = ""
    expected_permission_scope: str = ""
    expected_artifact_status: str = ""
    expected_stream_event_types: tuple[str, ...] = ()
    forbidden_agent_ids: tuple[str, ...] = ()
    min_events: int = 0


def load_cases(path: Path | None = None) -> tuple[AgentGatewayQualityCase, ...]:
    source = path or Path(__file__).with_name("cases.json")
    raw = json.loads(source.read_text(encoding="utf-8"))
    return tuple(
        AgentGatewayQualityCase(
            id=str(item["id"]),
            operation=str(item["operation"]),
            agent_id=str(item["agent_id"]),
            expected_status=str(item.get("expected_status", "")),
            expected_permission_scope=str(item.get("expected_permission_scope", "")),
            expected_artifact_status=str(item.get("expected_artifact_status", "")),
            expected_stream_event_types=tuple(str(value) for value in item.get("expected_stream_event_types", ())),
            forbidden_agent_ids=tuple(str(value) for value in item.get("forbidden_agent_ids", ())),
            min_events=int(item.get("min_events", 0)),
        )
        for item in raw
    )


__all__ = ["AgentGatewayQualityCase", "load_cases"]
