#!/usr/bin/env python
"""Reusable module-path codemod for the layered refactor.

Rewrites absolute ``personal_agent.<old>.<mod>`` references to
``personal_agent.<new>.<mod>`` for a given set of leaf modules, across
src / tests / evals / scripts. Because Stage 0 made every in-package import
absolute, this is a safe word-boundary text substitution — no AST resolution
needed. Handles four forms:

    from personal_agent.<old>.<mod> import ...   ->  from personal_agent.<new>.<mod> import ...
    import personal_agent.<old>.<mod>            ->  import personal_agent.<new>.<mod>
    personal_agent.<old>.<mod>.attr              ->  personal_agent.<new>.<mod>.attr
    from personal_agent.<old> import <mod>        ->  from personal_agent.<new> import <mod>

Usage:
    python scripts/_rename_modules.py --old personal_agent.core --new personal_agent.kernel \
        --modules models config evidence ... [--apply]
"""
from __future__ import annotations

import argparse
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEARCH_DIRS = ["src", "tests", "evals", "scripts"]


def build_rules(old: str, new: str, modules: list[str]) -> list[tuple[re.Pattern, str]]:
    rules: list[tuple[re.Pattern, str]] = []
    for mod in modules:
        # Rule A: dotted path personal_agent.<old>.<mod> (boundary after mod)
        rules.append((
            re.compile(rf"\b{re.escape(old)}\.{re.escape(mod)}\b"),
            f"{new}.{mod}",
        ))
    # Rule B: bare `from <old> import <mod>[, <mod2>...]` — only the moved names.
    # Handled per-line below since it needs to split the import list.
    return rules


def rewrite_text(text: str, old: str, new: str, modules: set[str], rules) -> tuple[str, int]:
    count = 0
    # Rule A + attribute/import dotted forms.
    for pat, repl in rules:
        text, n = pat.subn(repl, text)
        count += n
    # Rule B (multi-line): `from <old> import (\n  a,\n  b,\n)` — split moved names.
    paren_re = re.compile(
        rf"^(?P<indent>[ \t]*)from {re.escape(old)} import \((?P<body>[^)]*)\)",
        re.M,
    )

    def _split_paren(m: re.Match) -> str:
        nonlocal count
        indent, body = m.group("indent"), m.group("body")
        names = [n.strip() for n in body.replace("\n", " ").split(",") if n.strip()]
        moved = [n for n in names if n.split(" as ")[0].strip() in modules]
        stayed = [n for n in names if n.split(" as ")[0].strip() not in modules]
        if not moved:
            return m.group(0)
        count += len(moved)
        out_lines = [f"{indent}from {new} import {', '.join(moved)}"]
        if stayed:
            inner = "".join(f"{indent}    {n},\n" for n in stayed)
            out_lines.append(f"{indent}from {old} import (\n{inner}{indent})")
        return "\n".join(out_lines)

    text = paren_re.sub(_split_paren, text)

    # Rule B (single-line): `from <old> import a, b` where some names moved.
    line_re = re.compile(rf"^(\s*)from {re.escape(old)} import (.+)$", re.M)

    def _split_import(m: re.Match) -> str:
        nonlocal count
        indent, names_part = m.group(1), m.group(2)
        # Parenthesised imports are handled by paren_re above.
        if "(" in names_part:
            return m.group(0)
        names = [n.strip() for n in names_part.split(",")]
        moved = [n for n in names if n.split(" as ")[0].strip() in modules]
        stayed = [n for n in names if n.split(" as ")[0].strip() not in modules]
        if not moved:
            return m.group(0)
        count += len(moved)
        lines = [f"{indent}from {new} import {', '.join(moved)}"]
        if stayed:
            lines.append(f"{indent}from {old} import {', '.join(stayed)}")
        return "\n".join(lines)

    text = line_re.sub(_split_import, text)
    return text, count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--modules", nargs="+", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    modules = set(args.modules)
    rules = build_rules(args.old, args.new, args.modules)
    total = 0
    touched = 0
    for d in SEARCH_DIRS:
        base = os.path.join(REPO_ROOT, d)
        for dp, ds, fs in os.walk(base):
            ds[:] = [x for x in ds if x != "__pycache__"]
            for f in fs:
                if not f.endswith(".py"):
                    continue
                full = os.path.join(dp, f)
                src = open(full, encoding="utf-8").read()
                new_src, n = rewrite_text(src, args.old, args.new, modules, rules)
                if n:
                    total += n
                    touched += 1
                    if args.apply:
                        open(full, "w", encoding="utf-8", newline="").write(new_src)
    print(f"{'APPLIED' if args.apply else 'DRY-RUN'}: {total} substitutions across {touched} files "
          f"({args.old}.* -> {args.new}.* for {len(modules)} modules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
