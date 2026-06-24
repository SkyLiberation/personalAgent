#!/usr/bin/env python
"""Layer / cycle gate for the personal_agent package.

Builds a top-level subpackage import graph for ``src/personal_agent``, finds
strongly-connected components (import cycles at package granularity), and reports
edges that point "up" the target layer stack (a dependency from a lower layer to a
higher one). Used as the verification gate throughout the layered refactor.

Usage:
    python scripts/check_layers.py            # fail (exit 1) on any SCC>1 or up-edge
    python scripts/check_layers.py --baseline # print findings, always exit 0
    python scripts/check_layers.py --json      # machine-readable summary

The LAYER rank map intentionally covers BOTH the current package names and the
target layer names so the gate stays valid at every migration stage. Higher rank
= higher layer; a legal edge goes from higher rank to <= rank. An edge to a
strictly higher rank is a violation.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_ROOT = os.path.join(REPO_ROOT, "src", "personal_agent")
ROOT_PKG = "personal_agent"

# Higher number = higher layer. Dependencies must point to a rank <= source rank.
# Covers both legacy package names and the target layer package names so the gate
# works at every stage of the migration.
LAYER: dict[str, int] = {
    # ----- kernel (0) -----
    "kernel": 0,
    # ----- infra (1) -----
    "infra": 1,
    "storage": 1,  # legacy -> infra/storage
    # ----- application (3) -----
    # ``core`` now holds only application-tier leftovers (chunking, rerankers,
    # document_partition, candidate_enrichers) after its kernel modules moved to
    # kernel/ in stage 3; it dissolves into application/ in stage 5.
    "core": 3,
    # ----- memory (2) -----
    "memory": 2,
    "graphiti": 2,
    "ms_graphrag": 2,
    "structural_retriever": 2,
    "graphrag": 2,
    # ----- application (3) -----
    "application": 3,
    "capture": 3,
    "research": 3,
    "review": 3,
    "insight": 3,
    "knowledge": 3,
    "extract": 3,
    # ----- tools (4) -----
    "tools": 4,
    # ----- governance (5) -----
    "governance": 5,
    "policy": 5,
    "guardrails": 5,
    # ----- planning (6) -----
    "planning": 6,
    # ----- orchestration (7) -----
    "orchestration": 7,
    "agent": 7,  # legacy: splits into planning/orchestration/memory/application over stages
    # ----- adapters (8) -----
    "adapters": 8,
    "web": 8,
    "cli": 8,
    "feishu": 8,
}

LAYER_NAME = {
    0: "kernel", 1: "infra", 2: "memory", 3: "application",
    4: "tools", 5: "governance", 6: "planning", 7: "orchestration", 8: "adapters",
}


def discover_packages() -> set[str]:
    return {
        d for d in os.listdir(PKG_ROOT)
        if os.path.isdir(os.path.join(PKG_ROOT, d)) and not d.startswith("__")
    }


def top_pkg_of(rel_path: str) -> str | None:
    parts = rel_path.replace("\\", "/").split("/")
    return parts[0] if len(parts) > 1 else None


def resolve_relative(level: int, module: str | None, cur_parts: list[str]) -> str | None:
    """Resolve a relative import to its top-level personal_agent subpackage.

    cur_parts: path segments of the current file under personal_agent, file excluded.
               e.g. ['agent', 'orchestration_nodes'] for agent/orchestration_nodes/x.py
    """
    # level 1 = current package dir; level n climbs (n-1) dirs up.
    base = cur_parts[: len(cur_parts) - (level - 1)] if level - 1 <= len(cur_parts) else []
    target = base + ([module.split(".")[0]] if module else [])
    return target[0] if target else None


def build_graph(packages: set[str]) -> tuple[dict[str, set[str]], dict[tuple[str, str], set[str]]]:
    adj: dict[str, set[str]] = defaultdict(set)
    edge_files: dict[tuple[str, str], set[str]] = defaultdict(set)

    for dirpath, dirs, files in os.walk(PKG_ROOT):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, PKG_ROOT)
            src_pkg = top_pkg_of(rel)
            if src_pkg is None:
                continue
            cur_parts = rel.replace("\\", "/").split("/")[:-1]  # dirs only, drop filename
            try:
                tree = ast.parse(open(full, encoding="utf-8").read(), filename=full)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                dst_pkg = None
                if isinstance(node, ast.ImportFrom):
                    if node.level and node.level > 0:
                        dst_pkg = resolve_relative(node.level, node.module, cur_parts)
                    elif node.module and node.module.split(".")[0] == ROOT_PKG:
                        parts = node.module.split(".")
                        dst_pkg = parts[1] if len(parts) > 1 else None
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        parts = alias.name.split(".")
                        if parts[0] == ROOT_PKG and len(parts) > 1:
                            d = parts[1]
                            if d in packages and d != src_pkg:
                                adj[src_pkg].add(d)
                                edge_files[(src_pkg, d)].add(rel.replace("\\", "/"))
                    continue
                if dst_pkg and dst_pkg in packages and dst_pkg != src_pkg:
                    adj[src_pkg].add(dst_pkg)
                    edge_files[(src_pkg, dst_pkg)].add(rel.replace("\\", "/"))
    return adj, edge_files


def tarjan(adj: dict[str, set[str]], nodes: set[str]) -> list[list[str]]:
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    stack: list[str] = []
    counter = [0]
    out: list[list[str]] = []

    sys.setrecursionlimit(10000)

    def strongconnect(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack[v] = True
        for w in adj.get(v, ()):
            if w not in index:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif on_stack.get(w):
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                comp.append(w)
                if w == v:
                    break
            out.append(comp)

    for v in nodes:
        if v not in index:
            strongconnect(v)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true", help="print findings but exit 0")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    packages = discover_packages()
    adj, edge_files = build_graph(packages)

    sccs = tarjan(adj, packages)
    cycles = [sorted(c) for c in sccs if len(c) > 1]

    up_edges = []
    for (s, d), files in edge_files.items():
        rs, rd = LAYER.get(s), LAYER.get(d)
        if rs is not None and rd is not None and rs < rd:
            up_edges.append((rd - rs, s, d, sorted(files)))
    up_edges.sort(reverse=True)

    if args.json:
        print(json.dumps({
            "cycles": cycles,
            "up_edges": [{"gap": g, "src": s, "dst": d, "files": f} for g, s, d, f in up_edges],
        }, ensure_ascii=False, indent=2))
    else:
        print(f"packages: {len(packages)}  edges: {sum(len(v) for v in adj.values())}")
        print(f"\n== CYCLES (SCC>1): {len(cycles)} ==")
        for c in cycles:
            print(f"  [{len(c)}] {' -> '.join(c)}")
        if not cycles:
            print("  none (package graph is a DAG)")
        print(f"\n== UPWARD EDGES (violations): {len(up_edges)} ==")
        for gap, s, d, files in up_edges:
            ls, ld = LAYER_NAME[LAYER[s]], LAYER_NAME[LAYER[d]]
            print(f"  gap{gap} [{ls} -> {ld}]  {s} -> {d}")
            for fp in files:
                print(f"        {fp}")
        if not up_edges:
            print("  none")

    violations = len(cycles) + len(up_edges)
    if args.baseline:
        print(f"\n[baseline] violations={violations} (exit 0)")
        return 0
    if violations:
        print(f"\nFAIL: {len(cycles)} cycle(s), {len(up_edges)} upward edge(s)")
        return 1
    print("\nOK: no cycles, no upward edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
