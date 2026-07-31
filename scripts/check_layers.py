#!/usr/bin/env python
"""Fail-closed package dependency gate for the personal_agent architecture."""

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

# Direct dependencies only. Transitive reachability is deliberately not copied
# into every row: adding an edge requires an explicit architecture decision.
ALLOWED_DEPENDENCIES: dict[str, frozenset[str]] = {
    "kernel": frozenset(),
    "domain": frozenset({"kernel"}),
    "capabilities": frozenset({"kernel"}),
    "execution": frozenset({"capabilities", "kernel"}),
    "runtime": frozenset({"capabilities", "execution", "kernel"}),
    "memory": frozenset({"kernel"}),
    "application": frozenset({"capabilities", "domain", "kernel", "memory"}),
    "infra": frozenset({"application", "capabilities", "domain", "kernel", "runtime"}),
    "tools": frozenset({"application", "capabilities", "infra", "kernel", "memory"}),
    "governance": frozenset({"capabilities", "kernel", "runtime", "tools"}),
    "planning": frozenset({"capabilities", "execution", "governance", "kernel", "runtime", "tools"}),
    "agents": frozenset({"capabilities", "governance", "infra", "kernel", "runtime"}),
    "orchestration": frozenset({
        "agents", "application", "capabilities", "execution", "governance",
        "domain", "infra", "kernel", "memory", "planning", "runtime", "tools",
    }),
    "adapters": frozenset({
        "application", "domain", "infra", "kernel", "orchestration", "tools"
    }),
}


def contains_module(directory: str) -> bool:
    """Return whether a directory tree holds at least one importable module.

    A directory that only holds ``__pycache__`` artifacts is a removed package's
    build residue, not a package. Counting it produced a phantom
    ``unknown_packages`` violation that no source change could clear.
    """
    for dirpath, dirs, files in os.walk(directory):
        dirs[:] = [name for name in dirs if name != "__pycache__"]
        if any(name.endswith(".py") for name in files):
            return True
    return False


def discover_packages() -> set[str]:
    return {
        name for name in os.listdir(PKG_ROOT)
        if os.path.isdir(os.path.join(PKG_ROOT, name))
        and not name.startswith("__")
        and contains_module(os.path.join(PKG_ROOT, name))
    }


def top_pkg_of(rel_path: str) -> str | None:
    parts = rel_path.replace("\\", "/").split("/")
    return parts[0] if len(parts) > 1 else None


def resolve_relative(level: int, module: str | None, cur_parts: list[str]) -> str | None:
    base = cur_parts[: len(cur_parts) - (level - 1)] if level - 1 <= len(cur_parts) else []
    target = base + ([module.split(".")[0]] if module else [])
    return target[0] if target else None


def build_graph(packages: set[str]) -> tuple[dict[str, set[str]], dict[tuple[str, str], set[str]]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    edge_files: dict[tuple[str, str], set[str]] = defaultdict(set)
    for dirpath, dirs, files in os.walk(PKG_ROOT):
        dirs[:] = [name for name in dirs if name != "__pycache__"]
        for filename in files:
            if not filename.endswith(".py"):
                continue
            full = os.path.join(dirpath, filename)
            rel = os.path.relpath(full, PKG_ROOT)
            source = top_pkg_of(rel)
            if source is None:
                continue
            cur_parts = rel.replace("\\", "/").split("/")[:-1]
            with open(full, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=full)
            for node in ast.walk(tree):
                destinations: list[str] = []
                if isinstance(node, ast.ImportFrom):
                    if node.level:
                        destination = resolve_relative(node.level, node.module, cur_parts)
                    elif node.module and node.module.split(".")[0] == ROOT_PKG:
                        parts = node.module.split(".")
                        destination = parts[1] if len(parts) > 1 else None
                    else:
                        destination = None
                    if destination:
                        destinations.append(destination)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        parts = alias.name.split(".")
                        if parts[0] == ROOT_PKG and len(parts) > 1:
                            destinations.append(parts[1])
                for destination in destinations:
                    if destination in packages and destination != source:
                        adjacency[source].add(destination)
                        edge_files[(source, destination)].add(rel.replace("\\", "/"))
    return adjacency, edge_files


def tarjan(adjacency: dict[str, set[str]], nodes: set[str]) -> list[list[str]]:
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    output: list[list[str]] = []
    counter = 0

    def visit(node: str) -> None:
        nonlocal counter
        index[node] = low[node] = counter
        counter += 1
        stack.append(node)
        on_stack.add(node)
        for destination in adjacency.get(node, ()):
            if destination not in index:
                visit(destination)
                low[node] = min(low[node], low[destination])
            elif destination in on_stack:
                low[node] = min(low[node], index[destination])
        if low[node] == index[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            output.append(component)

    sys.setrecursionlimit(10_000)
    for node in sorted(nodes):
        if node not in index:
            visit(node)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    packages = discover_packages()
    unknown_packages = sorted(packages - set(ALLOWED_DEPENDENCIES))
    missing_packages = sorted(set(ALLOWED_DEPENDENCIES) - packages)
    adjacency, edge_files = build_graph(packages)
    cycles = [sorted(component) for component in tarjan(adjacency, packages) if len(component) > 1]
    forbidden_edges = [
        {"src": source, "dst": destination, "files": sorted(files)}
        for (source, destination), files in sorted(edge_files.items())
        if destination not in ALLOWED_DEPENDENCIES.get(source, frozenset())
    ]
    report = {
        "unknown_packages": unknown_packages,
        "missing_packages": missing_packages,
        "cycles": cycles,
        "forbidden_edges": forbidden_edges,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"packages={len(packages)} edges={sum(len(value) for value in adjacency.values())}")
        print(f"unknown_packages={unknown_packages or 'none'}")
        print(f"missing_packages={missing_packages or 'none'}")
        print(f"cycles={cycles or 'none'}")
        print(f"forbidden_edges={len(forbidden_edges)}")
        for edge in forbidden_edges:
            print(f"  {edge['src']} -> {edge['dst']}")
            for filename in edge["files"]:
                print(f"    {filename}")
    violations = len(unknown_packages) + len(missing_packages) + len(cycles) + len(forbidden_edges)
    if violations:
        print(f"FAIL: {violations} architecture violation(s)")
        return 1
    print("OK: explicit package DAG satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
