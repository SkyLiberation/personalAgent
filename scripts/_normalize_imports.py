#!/usr/bin/env python
"""One-shot: rewrite relative imports under src/personal_agent to absolute.

AST-guided, text-precise: for each ``from <dots>[module] import ...`` we compute
the absolute ``personal_agent.*`` target from the file's package path and replace
ONLY the ``from <dots>[module]`` prefix on that physical line. Comments, names,
and formatting elsewhere are untouched. Idempotent.

Run:  python scripts/_normalize_imports.py [--apply]
Without --apply it only reports the planned rewrites.
"""
from __future__ import annotations

import ast
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_ROOT = os.path.join(REPO_ROOT, "src", "personal_agent")
ROOT_PKG = "personal_agent"


def abs_module(level: int, module: str | None, pkg_parts: list[str]) -> str:
    """pkg_parts = package of the current file, e.g. ['personal_agent','agent','ask']."""
    base = pkg_parts[: len(pkg_parts) - (level - 1)] if level >= 1 else pkg_parts[:]
    if module:
        base = base + module.split(".")
    return ".".join(base)


def process(path: str, apply: bool) -> list[tuple[int, str, str]]:
    rel = os.path.relpath(path, os.path.join(REPO_ROOT, "src"))
    pkg_parts = rel.replace("\\", "/").split("/")[:-1]  # drop filename -> package of file
    src = open(path, encoding="utf-8").read()
    lines = src.splitlines(keepends=True)
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError:
        return []
    edits: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        target = abs_module(node.level, node.module, pkg_parts)
        ln = node.lineno - 1
        line = lines[ln]
        # match leading 'from <dots><optional dotted module>' on this line
        m = re.match(r"^(\s*from\s+)(\.+[A-Za-z_][\w.]*|\.+)(\s+import\b)", line)
        if not m:
            continue
        new_line = f"{m.group(1)}{target}{m.group(3)}" + line[m.end():]
        if new_line != line:
            edits.append((node.lineno, line.rstrip("\n"), new_line.rstrip("\n")))
            lines[ln] = new_line
    if apply and edits:
        open(path, "w", encoding="utf-8", newline="").write("".join(lines))
    return edits


def main() -> int:
    apply = "--apply" in sys.argv
    total = 0
    touched = 0
    for dp, ds, fs in os.walk(PKG_ROOT):
        ds[:] = [d for d in ds if d != "__pycache__"]
        for f in fs:
            if not f.endswith(".py"):
                continue
            full = os.path.join(dp, f)
            edits = process(full, apply)
            if edits:
                touched += 1
                total += len(edits)
                rel = os.path.relpath(full, REPO_ROOT).replace("\\", "/")
                for lineno, old, new in edits[:3]:
                    print(f"  {rel}:{lineno}\n    - {old.strip()}\n    + {new.strip()}")
                if len(edits) > 3:
                    print(f"    ... +{len(edits) - 3} more in this file")
    print(f"\n{'APPLIED' if apply else 'DRY-RUN'}: {total} rewrites across {touched} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
