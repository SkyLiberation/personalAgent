"""Parameter sweep for the LangExtract pre-extraction layer.

Runs the same long document through ``PreExtractService.extract`` with
different ``max_char_buffer`` and ``extraction_passes`` values to find a
config that produces a coarser SectionMap (~30 sections instead of 77)
without losing the graph_worthy / not-worthy split.

Bypasses Postgres — calls the service directly and reports a table.

Usage:
    python scripts/probe_extract_param_sweep.py [path_to_doc]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOC = REPO_ROOT / "docs" / "capture-ask-model-flow.md"


# (max_char_buffer, extraction_passes)
COMBOS: list[tuple[int, int]] = [
    (2000, 1),  # baseline matches current default
    (4000, 1),
    (6000, 1),
    (8000, 1),
    (4000, 2),  # passes>1 to confirm it INCREASES recall, not coalesces
]


def main() -> int:
    load_dotenv(override=True)
    doc_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DOC
    if not doc_path.exists():
        print(f"[sweep] doc not found: {doc_path}")
        return 2
    text = doc_path.read_text(encoding="utf-8")
    print(f"[sweep] doc={doc_path} chars={len(text)}")

    api_key = os.getenv("PERSONAL_AGENT_EXTRACT_API_KEY") or os.getenv("EMBEDDING_API_KEY")
    base_url = os.getenv(
        "PERSONAL_AGENT_EXTRACT_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    model_id = os.getenv("PERSONAL_AGENT_EXTRACT_MODEL", "qwen3-coder-flash")

    if not api_key:
        print("[sweep] missing api_key — abort")
        return 2

    from personal_agent.kernel.config import LangExtractConfig
    from personal_agent.extract.service import PreExtractService

    print(f"[sweep] model={model_id}")
    print()
    header = f"{'buffer':>8} {'passes':>7} {'sections':>9} {'worthy':>7} {'!worthy':>8} {'high':>5} {'med':>5} {'low':>5} {'secs':>6}"
    print(header)
    print("-" * len(header))

    best: tuple[int, int, int, dict] | None = None
    rows: list[dict] = []
    for buffer_size, passes in COMBOS:
        cfg = LangExtractConfig(
            api_key=api_key,
            base_url=base_url,
            model_id=model_id,
            max_char_buffer=buffer_size,
            extraction_passes=passes,
            max_workers=4,
            min_doc_chars=100,
            fallback_on_error=False,
        )
        svc = PreExtractService(cfg)
        t0 = time.monotonic()
        try:
            section_map = svc.extract(text)
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - t0
            print(f"{buffer_size:>8d} {passes:>7d}    ERROR ({type(exc).__name__}): {str(exc)[:50]} elapsed={elapsed:.1f}")
            continue
        elapsed = time.monotonic() - t0
        sections = section_map.sections
        worthy = sum(1 for s in sections if s.graph_worthy)
        not_worthy = len(sections) - worthy
        density = {"high": 0, "medium": 0, "low": 0}
        for s in sections:
            density[s.information_density] = density.get(s.information_density, 0) + 1
        row = {
            "max_char_buffer": buffer_size,
            "extraction_passes": passes,
            "sections": len(sections),
            "worthy": worthy,
            "not_worthy": not_worthy,
            "density_high": density["high"],
            "density_medium": density["medium"],
            "density_low": density["low"],
            "elapsed_seconds": round(elapsed, 1),
        }
        rows.append(row)
        print(
            f"{buffer_size:>8d} {passes:>7d} "
            f"{len(sections):>9d} {worthy:>7d} {not_worthy:>8d} "
            f"{density['high']:>5d} {density['medium']:>5d} {density['low']:>5d} "
            f"{elapsed:>6.1f}"
        )

    out = REPO_ROOT / "log" / "probe_param_sweep.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[sweep] results dumped to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
