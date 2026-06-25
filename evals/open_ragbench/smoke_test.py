"""Standalone smoke test that writes results directly to a file."""
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from evals.open_ragbench.adapter import corpus_to_notes, expected_note_ids
from evals.open_ragbench.loader import load_benchmark
from evals.open_ragbench.metrics import compute_report
from personal_agent.kernel.config import Settings
from personal_agent.memory.graphiti.store import GraphitiStore

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')

OUTPUT = Path("evals/open_ragbench/results/smoke_test_output.json")
MANIFEST = Path("evals/open_ragbench/results/smoke_test_manifest.json")
USER_ID = "ragbench_smoke_k25"
NOTE_MODE = os.getenv("RAGBENCH_GRAPHITI_NOTE_MODE", "parent_sections")

settings = Settings.from_env()
settings = settings.model_copy(
    update={
        "graphiti": settings.graphiti.model_copy(
            update={"search_strategy": "hybrid_rrf"}
        )
    }
)
store = GraphitiStore(settings)

print(f"Store configured: {store.configured()}", file=sys.stderr)

# Load 3 queries, relevant corpus
queries, docs = load_benchmark(num_queries=3, seed=42, corpus_mode="relevant")
notes = corpus_to_notes(docs, mode=NOTE_MODE)
print(f"Queries: {len(queries)}, Docs: {len(docs)}, Notes: {len(notes)}", file=sys.stderr)
print(f"Note mode: {NOTE_MODE}", file=sys.stderr)

# Clear and ingest
store.clear_user_group(USER_ID)

episode_to_note_id: dict[str, str] = {}
ingest_errors: list[str] = []
for i, note in enumerate(notes, 1):
    note = note.model_copy(update={"user_id": USER_ID})
    print(f"[{i}/{len(notes)}] Ingesting {note.id[:60]}...", file=sys.stderr)
    result = store.ingest_note(note, trace_id=f"smoke-{i}")
    if result.enabled and result.episode_uuid:
        episode_to_note_id[result.episode_uuid] = note.id
        print(f"  OK: episode={result.episode_uuid[:16]}... entities={result.entity_names}", file=sys.stderr)
    else:
        ingest_errors.append(f"{note.id}: {result.error}")
        print(f"  FAIL: {result.error}", file=sys.stderr)

if ingest_errors:
    print(f"\n{len(ingest_errors)} ingest errors:", file=sys.stderr)
    for err in ingest_errors[:5]:
        print(f"  - {err[:200]}", file=sys.stderr)

# Save manifest
MANIFEST.parent.mkdir(parents=True, exist_ok=True)
MANIFEST.write_text(json.dumps({
    "user_id": USER_ID,
    "episode_to_note_id": episode_to_note_id,
    "note_count": len(notes),
    "ingest_errors": ingest_errors,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nManifest: {len(episode_to_note_id)} episodes saved", file=sys.stderr)

# Ask queries
rankings: list[tuple[str, list[str]]] = []
relevance: dict[str, set[str]] = {}
for query in queries:
    print(f"Asking: {query.query_text[:60]}...", file=sys.stderr)
    result = store.ask(query.query_text, USER_ID)
    if result.enabled:
        ranked = []
        seen = set()
        for hit in result.citation_hits:
            note_id = episode_to_note_id.get(hit.episode_uuid)
            if note_id and note_id not in seen:
                ranked.append(note_id)
                seen.add(note_id)
                if len(ranked) >= 10:
                    break
        for ep_uuid in result.related_episode_uuids:
            note_id = episode_to_note_id.get(ep_uuid)
            if note_id and note_id not in seen:
                ranked.append(note_id)
                seen.add(note_id)
                if len(ranked) >= 10:
                    break
        rankings.append((query.query_id, ranked))
        sec_id, parent_id = expected_note_ids(query)
        relevance[query.query_id] = {sec_id, parent_id}
        print(f"  Ranked: {len(ranked)} notes", file=sys.stderr)
    else:
        print(f"  FAIL: {result.error}", file=sys.stderr)

# Compute and save results
report = compute_report(rankings, relevance)
results = {
    "strategy": "graphiti_hybrid_rrf",
    "num_queries": len(queries),
    "num_docs": len(docs),
    "num_notes": len(notes),
    "num_episodes": len(episode_to_note_id),
    "note_mode": NOTE_MODE,
    "ingest_errors": len(ingest_errors),
    "metrics": report.as_dict(),
}
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nResults written to {OUTPUT}", file=sys.stderr)
print(report.summary(), file=sys.stderr)
