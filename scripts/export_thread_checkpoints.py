from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
CURRENT_CHECKPOINT_SCHEMA_VERSION = "step_execution_v2"


def _ensure_src_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


def _asset_output_path(thread_id: str, *, raw: bool = False) -> Path:
    safe_thread_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", thread_id).strip("_.")
    suffix = "-raw" if raw else ""
    return ASSETS_DIR / f"checkpoints-{safe_thread_id or 'thread'}{suffix}.json"


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (Path, UUID)):
        return str(value)
    if isinstance(value, bytes):
        return {
            "__type__": "bytes",
            "base64": base64.b64encode(value).decode("ascii"),
        }
    try:
        json.dumps(value)
    except TypeError:
        return repr(value)
    return value


def _application_state(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _jsonable(value)
        for key, value in values.items()
        if not key.startswith("branch:") and key != "__start__"
    }


def _checkpoint_schema(values: dict[str, Any]) -> str:
    if "plan" in values:
        return "legacy_plan_v1"
    if "step_execution" in values:
        return CURRENT_CHECKPOINT_SCHEMA_VERSION
    return "unknown"


def _step_execution_summary(values: dict[str, Any]) -> dict[str, Any]:
    step_execution = values.get("step_execution")
    if isinstance(step_execution, BaseModel):
        step_execution = step_execution.model_dump(mode="json")
    if not isinstance(step_execution, dict):
        return {
            "schema_version": _checkpoint_schema(values),
            "step_count": 0,
            "current_step_index": 0,
            "aborted": False,
            "result_keys": [],
            "statuses": {},
        }
    steps = step_execution.get("steps") or []
    statuses: dict[str, int] = {}
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, BaseModel):
                step = step.model_dump(mode="json")
            status = step.get("status") if isinstance(step, dict) else None
            if status:
                statuses[str(status)] = statuses.get(str(status), 0) + 1
    results = step_execution.get("results") or {}
    return {
        "schema_version": _checkpoint_schema(values),
        "step_count": len(steps) if isinstance(steps, list) else 0,
        "current_step_index": step_execution.get("current_step_index", 0),
        "aborted": bool(step_execution.get("aborted", False)),
        "result_keys": sorted(str(key) for key in results) if isinstance(results, dict) else [],
        "statuses": statuses,
    }


def collect_thread_checkpoints(
    checkpointer: Any, thread_id: str, *, raw: bool = False
) -> dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}
    records = []
    for checkpoint_tuple in checkpointer.list(config):
        if raw:
            records.append(
                {
                    "config": _jsonable(checkpoint_tuple.config),
                    "checkpoint": _jsonable(checkpoint_tuple.checkpoint),
                    "metadata": _jsonable(checkpoint_tuple.metadata),
                    "parent_config": _jsonable(checkpoint_tuple.parent_config),
                    "pending_writes": _jsonable(checkpoint_tuple.pending_writes),
                }
            )
            continue

        checkpoint = checkpoint_tuple.checkpoint or {}
        metadata = checkpoint_tuple.metadata or {}
        values = checkpoint.get("channel_values", {})
        records.append(
            {
                "checkpoint_schema_version": _checkpoint_schema(values),
                "step": metadata.get("step"),
                "source": metadata.get("source"),
                "timestamp": checkpoint.get("ts"),
                "checkpoint_id": checkpoint.get("id"),
                "step_execution": _step_execution_summary(values),
                "state": _application_state(values),
            }
        )
    return {
        "thread_id": thread_id,
        "current_checkpoint_schema_version": CURRENT_CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_count": len(records),
        "format": "raw" if raw else "state_timeline",
        "checkpoints": records,
    }


def main() -> int:
    _ensure_src_on_path()

    from langgraph.checkpoint.postgres import PostgresSaver
    from personal_agent.core.config import Settings
    from personal_agent.storage.postgres_common import normalize_postgres_url

    settings = Settings.from_env()
    parser = argparse.ArgumentParser(
        description="Export persisted LangGraph checkpoint state for one thread_id as JSON."
    )
    parser.add_argument(
        "thread_id", help="Exact LangGraph configurable thread_id to export."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output JSON path. Defaults to scripts/assets/checkpoints-<thread_id>.json.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Include raw LangGraph tuple internals. Defaults output to a separate *-raw.json file.",
    )
    args = parser.parse_args()

    output_path = args.output or _asset_output_path(args.thread_id, raw=args.raw)
    with PostgresSaver.from_conn_string(
        normalize_postgres_url(settings.postgres_url)
    ) as checkpointer:
        checkpointer.setup()
        payload = collect_thread_checkpoints(
            checkpointer, args.thread_id, raw=args.raw
        )

    if not payload["checkpoints"]:
        parser.error(f"no checkpoints found for thread_id: {args.thread_id}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
