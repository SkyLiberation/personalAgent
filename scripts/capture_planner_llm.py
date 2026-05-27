"""Capture interface called by DefaultTaskPlanner._plan_with_llm.

One function — call it with the raw LLM response content right after receiving it.
Parses the JSON internally so truncated/failed responses are also captured.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
DEFAULT_OUTPUT = ASSETS_DIR / "planner-llm-captures.jsonl"


def write_plan_capture(
    content: str,
    *,
    intent: str = "",
    context: str = "",
    prompt: str = "",
    output_path: Path | str | None = None,
) -> None:
    """Append the raw LLM response (and parsed payload if valid) to the JSONL file."""
    dest = Path(output_path) if output_path else DEFAULT_OUTPUT
    payload = None
    parse_error = None
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        parse_error = str(exc)
    record = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "intent": intent,
        "context": context,
        "prompt": prompt,
        "raw": content,
        "payload": payload,
        "parse_error": parse_error,
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
