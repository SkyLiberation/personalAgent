"""End-to-end smoke test for the LangExtract pre-extraction layer.

Drives a real ingestion through ``AgentService.execute_capture`` against a
locally running Postgres + Neo4j stack and inspects the resulting note +
chunk routing decisions. Does NOT mock anything.

Prerequisites:
  * Postgres reachable at PERSONAL_AGENT_POSTGRES_URL
  * Neo4j reachable per .env settings
  * PERSONAL_AGENT_EXTRACT_API_KEY (or EMBEDDING_API_KEY) populated
  * langextract installed (already in pyproject)

Usage:
    python scripts/probe_capture_end_to_end.py [path_to_long_doc.md]

Defaults to docs/capture-ask-model-flow.md when no path is provided.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOC = REPO_ROOT / "docs" / "capture-ask-model-flow.md"


def _safe(value: object) -> str:
    text = "" if value is None else str(value)
    return text.encode("ascii", errors="replace").decode("ascii")


def _print_chunk_summary(chunks: list, *, label: str) -> None:
    print(f"\n[{label}] count={len(chunks)}")
    if not chunks:
        return
    worthy = sum(1 for c in chunks if c.graph_worthy is True)
    not_worthy = sum(1 for c in chunks if c.graph_worthy is False)
    unset = sum(1 for c in chunks if c.graph_worthy is None)
    skipped = sum(1 for c in chunks if c.graph_sync_status == "skipped")
    pending = sum(1 for c in chunks if c.graph_sync_status == "pending")
    print(
        f"[{label}] graph_worthy: True={worthy} False={not_worthy} None={unset}"
    )
    print(
        f"[{label}] graph_sync_status: skipped={skipped} pending={pending}"
    )
    for i, chunk in enumerate(chunks[:8]):
        title = _safe(chunk.title)[:40]
        topic = _safe(chunk.preextract_topic or "")[:40]
        print(
            f"  [{i}] worthy={chunk.graph_worthy} "
            f"sync={chunk.graph_sync_status} "
            f"title={title!r} topic={topic!r} span={chunk.source_span}"
        )
    if len(chunks) > 8:
        print(f"  ... and {len(chunks) - 8} more")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
    )
    load_dotenv(override=True)

    # Force-enable LangExtract regardless of .env default; this is a probe.
    if not os.getenv("PERSONAL_AGENT_EXTRACT_API_KEY"):
        if not os.getenv("EMBEDDING_API_KEY"):
            print("[probe] PERSONAL_AGENT_EXTRACT_API_KEY / EMBEDDING_API_KEY missing")
            return 2
    os.environ.setdefault("PERSONAL_AGENT_EXTRACT_MIN_DOC_CHARS", "200")

    doc_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DOC
    if not doc_path.exists():
        print(f"[probe] doc not found: {doc_path}")
        return 2

    text = doc_path.read_text(encoding="utf-8")
    print(f"[probe] doc={doc_path} chars={len(text)}")

    from personal_agent.agent.service import AgentService
    from personal_agent.core.config import LangExtractConfig, Settings

    settings = Settings.from_env()
    # Top up min_doc_chars from CLI override; everything else stays as configured.
    settings = settings.model_copy(
        update={
            "langextract": LangExtractConfig(
                api_key=settings.langextract.api_key
                or os.getenv("EMBEDDING_API_KEY"),
                base_url=settings.langextract.base_url,
                model_id=settings.langextract.model_id,
                max_char_buffer=settings.langextract.max_char_buffer,
                extraction_passes=settings.langextract.extraction_passes,
                max_workers=settings.langextract.max_workers,
                min_doc_chars=int(
                    os.getenv("PERSONAL_AGENT_EXTRACT_MIN_DOC_CHARS", "200")
                ),
                fallback_on_error=settings.langextract.fallback_on_error,
            )
        }
    )
    print(
        f"[probe] langextract model={settings.langextract.model_id} "
        f"min_doc_chars={settings.langextract.min_doc_chars}"
    )
    if not settings.langextract.api_key:
        print("[probe] langextract.api_key missing — abort")
        return 2

    service = AgentService(settings=settings)

    print("[probe] running execute_capture …")
    result = service.execute_capture(
        text=text,
        source_type="text",
        user_id=settings.default_user,
        source_ref=str(doc_path),
    )

    note = result.note
    print("\n=== parent note ===")
    print(f"  id={note.id}")
    print(f"  title={_safe(note.title)[:60]!r}")
    print(f"  preextract_status={note.preextract_status}")
    print(f"  preextract_topic={_safe(note.preextract_topic or '')[:80]!r}")
    print(f"  graph_worthy={note.graph_worthy}")
    print(f"  graph_sync_status={note.graph_sync_status}")
    print(f"  graph_sync_error={_safe(note.graph_sync_error or '')[:120]}")
    print(f"  entity_names={[_safe(e) for e in note.entity_names[:8]]}")
    section_map = note.section_map
    if section_map:
        print(
            f"  section_map.doc_topic={_safe(section_map.get('doc_topic', ''))[:60]!r}"
        )
        print(f"  section_map.sections={len(section_map.get('sections', []))}")

    _print_chunk_summary(result.chunk_notes, label="chunk_notes")

    print("\n=== assertions ===")
    asserts = []
    asserts.append(("preextract_status set", note.preextract_status is not None))
    asserts.append(("section_map populated when ok",
                    note.preextract_status != "ok" or note.section_map is not None))
    asserts.append(("any chunk_worthy=False routed to skipped",
                    all(c.graph_sync_status == "skipped"
                        for c in result.chunk_notes if c.graph_worthy is False)))
    asserts.append(("any chunk_worthy=True routed to pending or synced",
                    all(c.graph_sync_status in {"pending", "synced"}
                        for c in result.chunk_notes if c.graph_worthy is True)))
    failed = 0
    for label, ok in asserts:
        marker = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"  [{marker}] {label}")

    if section_map:
        out_path = REPO_ROOT / "log" / "probe_capture_section_map.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(section_map, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"\n[probe] section_map dumped to {out_path}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
