"""Adapters + CLI for the RAG-quality harness.

The scorer only knows :class:`RunOutput`. This module bridges the live pipeline
to that projection two ways:

  - ``run_output_from_context`` — from a full :class:`AskRunContext` (richest:
    has evidence_pool, context_pack, verification). Use when driving the
    pipeline yourself or replaying a serialized context.
  - ``run_output_from_result`` — from the public :class:`AskResult` (answer +
    evidence + matches; no verification). Use behind ``execute_ask``.

The CLI replays a JSON file of serialized ``AskRunContext`` payloads (the
offline, DB-free path the design doc calls out) and prints / writes a report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .dataset import RunOutput, default_cases_path, load_cases
from .scorer import score_all


def _evidence_text(item) -> str:
    parts = [
        str(getattr(item, "title", "") or ""),
        str(getattr(item, "fact", "") or ""),
        str(getattr(item, "snippet", "") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


def _evidence_id(item) -> str:
    return str(getattr(item, "source_id", "") or getattr(item, "evidence_id", "") or "")


def run_output_from_context(ctx) -> RunOutput:
    """Project a live or replayed AskRunContext into a RunOutput."""
    pool = list(getattr(ctx, "evidence_pool", []) or [])
    pack = getattr(ctx, "context_pack", None)
    selected = list(getattr(pack, "evidence", []) or []) if pack else []
    verification = getattr(ctx, "verification", None)
    checks = list(getattr(verification, "claim_checks", []) or []) if verification else []
    counter = sum(
        1 for item in pool
        if (getattr(item, "metadata", {}) or {}).get("retrieved_by") == "contrastive"
    )
    return RunOutput(
        ranked_evidence_ids=[_evidence_id(e) for e in pool],
        selected_evidence_ids=[_evidence_id(e) for e in selected],
        selected_evidence_texts=[_evidence_text(e) for e in selected],
        answer=str(getattr(ctx, "answer", "") or ""),
        claim_verdicts=[c.status for c in checks],
        counter_evidence_found=counter,
    )


def run_output_from_result(result, verification=None) -> RunOutput:
    """Project an AskResult (+ optional VerificationResult) into a RunOutput."""
    evidence = list(getattr(result, "evidence", []) or [])
    checks = list(getattr(verification, "claim_checks", []) or []) if verification else []
    counter = sum(
        1 for item in evidence
        if (getattr(item, "metadata", {}) or {}).get("retrieved_by") == "contrastive"
    )
    return RunOutput(
        ranked_evidence_ids=[_evidence_id(e) for e in evidence],
        selected_evidence_ids=[_evidence_id(e) for e in evidence],
        selected_evidence_texts=[_evidence_text(e) for e in evidence],
        answer=str(getattr(result, "answer", "") or ""),
        claim_verdicts=[c.status for c in checks],
        counter_evidence_found=counter,
    )


def replay_contexts(payloads_path: str | Path) -> dict[str, RunOutput]:
    """Load a JSON map ``{case_id: ask_run_context_payload}`` and project each
    into a RunOutput via ``AskRunContext.from_artifact_payload`` — fully offline,
    no DB, no LLM."""
    from personal_agent.agent.ask.context import AskRunContext

    raw = json.loads(Path(payloads_path).read_text(encoding="utf-8"))
    runs: dict[str, RunOutput] = {}
    for case_id, payload in raw.items():
        ctx = AskRunContext.from_artifact_payload(payload)
        runs[case_id] = run_output_from_context(ctx)
    return runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RAG-quality offline eval gate")
    parser.add_argument(
        "--contexts", required=True,
        help="JSON file mapping case_id -> serialized AskRunContext payload",
    )
    parser.add_argument("--cases", default=None, help="cases.json (defaults to bundled set)")
    parser.add_argument("--output", default=None, help="write the report JSON here")
    args = parser.parse_args(argv)

    cases = load_cases(args.cases or default_cases_path())
    runs = replay_contexts(args.contexts)
    report = score_all(cases, runs)
    print(report.summary())
    if args.output:
        Path(args.output).write_text(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(f"\nReport written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
