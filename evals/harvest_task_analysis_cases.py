"""Harvest real TaskAnalyzer outputs from logs into draft golden-set cases.

This is the data-collection half of a real-environment golden set: the runners
already score the real *system*, but the *data* is hand-written. This harvester
turns real logged interactions into draft cases, so the golden set can grow from
actual usage instead of invented inputs.

It parses ``task_analysis.completed`` lines from a log file and emits draft
``TaskAnalysisEvalCase``-shaped
dicts. Crucially it does NOT invent gold labels: it records the model's OWN
decision under ``observed_*`` and leaves ``expected_*`` UNSET, so a human must
confirm or correct each draft before it becomes a real golden case. That human
judgment is what makes it "gold".

Usage:
    uv run python -m evals.harvest_task_analysis_cases --log log/run.log \
        --out evals/task_analysis_quality/harvested_draft.json
    # then review harvested_draft.json, fill expected_*, fold good ones into
    # cases.json (and DELETE the ones the model got wrong, after fixing the bug).

Deliberately stdlib-only and dependency-free so it can run anywhere a log exists.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_DECISION_RE = re.compile(r"task_analysis\.completed\s*\|\s*(\{.*\})\s*$")


def parse_task_analyses(log_text: str) -> list[dict]:
    """Extract structured task-analysis payloads from a log body."""
    out: list[dict] = []
    for line in log_text.splitlines():
        m = _DECISION_RE.search(line)
        if not m:
            continue
        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        out.append(payload)
    return out


def analyses_to_draft_cases(payloads: list[dict]) -> list[dict]:
    """Turn task-analysis payloads into deduped draft cases.

    Dedup is by ``text_preview`` (the input) — the same input logged twice is
    one case. The model's own decision is recorded under ``observed_*`` as a
    SUGGESTION; ``expected_*`` is left blank for human annotation.
    """
    seen: set[str] = set()
    drafts: list[dict] = []
    for p in payloads:
        text = str(p.get("text_preview", "") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        observed_result_contracts = list(p.get("result_contracts", []) or [])
        clarify = str(p.get("outcome", "")) == "clarify"
        drafts.append({
            "id": f"harvested-{len(drafts) + 1:03d}",
            "text": text,
            "source_type": str(p.get("source_type", "text") or "text"),
            # --- model's own decision (SUGGESTION, not gold) ---
            "observed_outcome": "clarify" if clarify else "ready",
            "observed_result_contracts": observed_result_contracts,
            "observed_missing_information": list(p.get("missing_information", []) or []),
            # --- to be filled by a human reviewer, then folded into cases.json ---
            "expected_outcome": "",
            "expected_result_contracts": [],
            "expected_missing_info": [],
            "_review": "confirm or correct expected_* vs observed_*; delete if model was wrong (after fixing the bug)",
        })
    return drafts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harvest task analyses into draft golden cases")
    parser.add_argument("--log", default="log/run.log", help="log file to parse")
    parser.add_argument("--out", default=None, help="write draft cases JSON here (else stdout)")
    args = parser.parse_args(argv)

    log_path = Path(args.log)
    if not log_path.exists():
        print(f"log file not found: {log_path}")
        return 1
    payloads = parse_task_analyses(log_path.read_text(encoding="utf-8", errors="replace"))
    drafts = analyses_to_draft_cases(payloads)
    body = json.dumps(drafts, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(body, encoding="utf-8")
        print(f"Harvested {len(drafts)} draft case(s) from {len(payloads)} decision(s) -> {args.out}")
    else:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
