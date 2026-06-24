"""Graph extraction quality health report.

Queries Postgres for all synced notes and computes aggregate quality metrics.
Optionally queries Neo4j for graph-level health (node/edge counts, degree, etc).

Usage:
    python scripts/probe_graph_health.py [--user USER] [--neo4j]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    load_dotenv(override=True)
    parser = argparse.ArgumentParser(description="Graph extraction quality health report")
    parser.add_argument("--user", default=None, help="Filter by user_id (default: all)")
    parser.add_argument("--neo4j", action="store_true", help="Include Neo4j graph-level metrics")
    args = parser.parse_args()

    from personal_agent.kernel.config import Settings
    from personal_agent.storage.postgres_memory_store import PostgresMemoryStore

    settings = Settings.from_env()
    if not settings.postgres_url:
        print("[health] PERSONAL_AGENT_POSTGRES_URL not set — abort")
        return 2

    store = PostgresMemoryStore(data_dir=settings.data_dir, postgres_url=settings.postgres_url)

    user_filter = args.user or settings.default_user
    notes = store.list_notes(user_filter)
    synced = [n for n in notes if n.graph_sync_status == "synced"]
    skipped = [n for n in notes if n.graph_sync_status == "skipped"]
    failed = [n for n in notes if n.graph_sync_status == "failed"]
    pending = [n for n in notes if n.graph_sync_status == "pending"]

    print(f"=== Graph Health Report (user={user_filter}) ===\n")
    print(f"Total notes: {len(notes)}")
    print(f"  synced:  {len(synced)}")
    print(f"  skipped: {len(skipped)}")
    print(f"  failed:  {len(failed)}")
    print(f"  pending: {len(pending)}")

    if not synced:
        print("\nNo synced notes — nothing to aggregate.")
        return 0

    total_entities = sum(len(n.entity_names) for n in synced)
    total_relations = sum(len(n.relation_facts) for n in synced)
    avg_entities = total_entities / len(synced)
    avg_relations = total_relations / len(synced)

    zero_entity_notes = [n for n in synced if n.graph_quality_zero_entities is True]
    weak_relation_notes = [n for n in synced if n.graph_quality_weak_relations_only is True]

    all_fact_lengths = []
    for n in synced:
        all_fact_lengths.extend(len(f) for f in n.relation_facts if f.strip())
    avg_fact_length = sum(all_fact_lengths) / len(all_fact_lengths) if all_fact_lengths else 0.0

    print(f"\n--- Extraction Metrics ---")
    print(f"Total entities:  {total_entities}")
    print(f"Total relations: {total_relations}")
    print(f"Avg entities/note:  {avg_entities:.1f}")
    print(f"Avg relations/note: {avg_relations:.1f}")
    print(f"Avg fact length:    {avg_fact_length:.1f} chars")

    print(f"\n--- Quality Anomalies ---")
    zero_rate = len(zero_entity_notes) / len(synced) * 100
    weak_rate = len(weak_relation_notes) / len(synced) * 100
    print(f"Zero-entity anomalies: {len(zero_entity_notes)}/{len(synced)} ({zero_rate:.1f}%)")
    print(f"Weak-relations-only:   {len(weak_relation_notes)}/{len(synced)} ({weak_rate:.1f}%)")

    if zero_entity_notes:
        print(f"\n  Zero-entity notes:")
        for n in zero_entity_notes[:10]:
            topic = (n.preextract_topic or n.title or "")[:40]
            print(f"    {n.id[:8]}... topic={topic!r}")

    if weak_relation_notes:
        print(f"\n  Weak-relation notes:")
        for n in weak_relation_notes[:10]:
            topic = (n.preextract_topic or n.title or "")[:40]
            facts = n.relation_facts[:3]
            print(f"    {n.id[:8]}... topic={topic!r} facts={facts}")

    if args.neo4j:
        _print_neo4j_health(settings)

    print(f"\n=== Done ===")
    return 0


def _print_neo4j_health(settings) -> None:
    """Query Neo4j for graph-level health metrics."""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("\n[neo4j] neo4j driver not installed — skip")
        return

    uri = settings.graphiti.uri
    user = settings.graphiti.user
    password = settings.graphiti.password

    print(f"\n--- Neo4j Graph Health ({uri}) ---")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            edge_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            avg_degree = session.run(
                "MATCH (n) RETURN avg(size([(n)--() | 1])) AS d"
            ).single()["d"] or 0.0
            isolated = session.run(
                "MATCH (n) WHERE NOT (n)--() RETURN count(n) AS c"
            ).single()["c"]

            print(f"Node count:     {node_count}")
            print(f"Edge count:     {edge_count}")
            print(f"Avg degree:     {avg_degree:.2f}")
            print(f"Isolated nodes: {isolated} ({isolated/max(node_count,1)*100:.1f}%)")
        driver.close()
    except Exception as exc:
        print(f"[neo4j] connection failed: {exc}")


if __name__ == "__main__":
    sys.exit(main())
