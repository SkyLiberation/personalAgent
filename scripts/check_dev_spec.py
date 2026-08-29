"""Validate progressive-disclosure engineering instructions and route accuracy."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
CLAUDE = ROOT / "CLAUDE.md"
SPEC_DIR = ROOT / "docs" / "devSpec"
CASES = SPEC_DIR / "recognition-cases.json"
MODULE_INSTRUCTIONS = [ROOT / "docs" / "AGENTS.md", ROOT / "evals" / "AGENTS.md"]
MODULE_OVERLAYS = {
    "docs": "docs/AGENTS.md",
    "evals": "evals/AGENTS.md",
}
MAX_INSTRUCTION_BYTES = 32 * 1024
MAX_INSTRUCTION_LINES = 200

ROUTE_RE = re.compile(
    r"^\| `(?P<code>[A-Z]{3})` \| (?P<signals>.+?) \| "
    r"\[[^]]+\]\((?P<path>[^)]+)\) \|$"
)
LINK_RE = re.compile(r"(?<!!)\[[^]]*\]\(([^)]+)\)")
ASCII_WORD_RE = re.compile(r"[a-z0-9_]+")
CJK_RE = re.compile(r"[\u3400-\u9fff]")


@dataclass(frozen=True)
class Route:
    code: str
    signals: str
    path: Path


def fail(message: str) -> None:
    raise AssertionError(message)


def parse_routes(text: str) -> list[Route]:
    routes: list[Route] = []
    for line in text.splitlines():
        match = ROUTE_RE.match(line)
        if match:
            routes.append(
                Route(
                    code=match.group("code"),
                    signals=match.group("signals"),
                    path=ROOT / match.group("path"),
                )
            )
    if len(routes) != 9:
        fail(f"expected 9 task routes, found {len(routes)}")
    if len({route.code for route in routes}) != len(routes):
        fail("task route codes are not unique")
    return routes


def normalized_text(text: str) -> str:
    return "".join(
        character.lower()
        for character in text
        if character.isalnum() or character == "_"
    )


def features(text: str) -> set[str]:
    lowered = text.lower()
    result = set(ASCII_WORD_RE.findall(lowered))
    cjk = "".join(CJK_RE.findall(text))
    result.update(cjk[index : index + 2] for index in range(max(0, len(cjk) - 1)))
    return result


def route_score(task: str, route: Route) -> float:
    task_normalized = normalized_text(task)
    phrases = re.split(r"[、，,；;]", route.signals)
    direct = sum(
        100.0 + len(phrase_normalized)
        for phrase in phrases
        if (phrase_normalized := normalized_text(phrase))
        and phrase_normalized in task_normalized
    )
    task_features = features(task)
    signal_features = features(route.signals)
    overlap = len(task_features & signal_features)
    union = len(task_features | signal_features) or 1
    return direct + overlap / union


def predict(task: str, routes: list[Route]) -> str:
    ranked = sorted(
        ((route_score(task, route), route.code) for route in routes),
        key=lambda item: (-item[0], item[1]),
    )
    return ranked[0][1]


def identify_module_overlay(target: str) -> str | None:
    first_part = Path(target).parts[0] if Path(target).parts else ""
    return MODULE_OVERLAYS.get(first_part)


def check_links(paths: list[Path]) -> int:
    checked = 0
    for source in paths:
        text = source.read_text(encoding="utf-8")
        if text.count("```") % 2:
            fail(f"unbalanced fenced code block: {source.relative_to(ROOT)}")
        for raw_target in LINK_RE.findall(text):
            target = raw_target.strip().strip("<>").split("#", 1)[0]
            if not target or re.match(r"^[a-z]+://", target):
                continue
            resolved = (source.parent / target).resolve()
            if not resolved.exists():
                fail(f"broken local link in {source.relative_to(ROOT)}: {raw_target}")
            checked += 1
    return checked


def main() -> int:
    agents_bytes = AGENTS.read_bytes()
    claude_bytes = CLAUDE.read_bytes()
    if agents_bytes != claude_bytes:
        fail("AGENTS.md and CLAUDE.md are not byte-identical")
    if len(agents_bytes) >= MAX_INSTRUCTION_BYTES:
        fail(
            f"main instruction entry is {len(agents_bytes)} bytes; "
            f"must stay below {MAX_INSTRUCTION_BYTES}"
        )
    line_count = len(AGENTS.read_text(encoding="utf-8").splitlines())
    if line_count > MAX_INSTRUCTION_LINES:
        fail(
            f"main instruction entry is {line_count} lines; "
            f"must not exceed {MAX_INSTRUCTION_LINES}"
        )
    for module_instruction in MODULE_INSTRUCTIONS:
        combined_size = len(agents_bytes) + len(module_instruction.read_bytes())
        if combined_size >= MAX_INSTRUCTION_BYTES:
            fail(
                f"root plus {module_instruction.relative_to(ROOT)} is "
                f"{combined_size} bytes; must stay below {MAX_INSTRUCTION_BYTES}"
            )

    agents_text = AGENTS.read_text(encoding="utf-8")
    routes = parse_routes(agents_text)
    for route in routes:
        if not route.path.is_file():
            fail(f"route {route.code} points to missing file: {route.path}")
        first_line = route.path.read_text(encoding="utf-8").splitlines()[0]
        if f"（{route.code}）" not in first_line:
            fail(f"route {route.code} is not declared in {route.path.name} title")

    fixture = json.loads(CASES.read_text(encoding="utf-8"))
    cases = fixture["cases"]
    results = [
        (case["id"], case["expected"], predict(case["task"], routes)) for case in cases
    ]
    correct = sum(expected == actual for _, expected, actual in results)
    accuracy = correct / len(results) if results else 0.0
    misses = [result for result in results if result[1] != result[2]]
    overlay_results = []
    for case in fixture["module_overlay_cases"]:
        target = ROOT / case["path"]
        if not target.exists():
            fail(f"module overlay case points to missing path: {case['path']}")
        overlay_results.append(
            (
                case["id"],
                case["expected"],
                identify_module_overlay(case["path"]),
            )
        )
    overlay_correct = sum(expected == actual for _, expected, actual in overlay_results)
    overlay_misses = [result for result in overlay_results if result[1] != result[2]]

    link_sources = [
        AGENTS,
        CLAUDE,
        ROOT / "docs" / "README.md",
        *MODULE_INSTRUCTIONS,
    ]
    link_sources.extend(sorted(SPEC_DIR.glob("*.md")))
    link_sources.extend(sorted((ROOT / "docs" / "agentRef").glob("*.md")))
    checked_links = check_links(link_sources)

    baseline_bytes = fixture["baseline"]["bytes_per_entry"]
    reduction = 1.0 - len(agents_bytes) / baseline_bytes
    digest = hashlib.sha256(agents_bytes).hexdigest().upper()
    print("devSpec validation: PASS" if not misses else "devSpec validation: FAIL")
    print(f"entry sync: byte-identical, sha256={digest}")
    print(
        f"entry size: {len(agents_bytes)} bytes, {line_count} lines, "
        f"reduction={reduction:.2%}"
    )
    print(f"routes: {len(routes)}/9")
    print(
        "module instruction chains: "
        + ", ".join(
            f"{path.parent.name}={len(agents_bytes) + len(path.read_bytes())} bytes"
            for path in MODULE_INSTRUCTIONS
        )
    )
    print(f"top-1 primary spec accuracy: {correct}/{len(results)} ({accuracy:.2%})")
    print(
        "module overlay accuracy: "
        f"{overlay_correct}/{len(overlay_results)} "
        f"({overlay_correct / len(overlay_results):.2%})"
    )
    print(f"local links: {checked_links} checked")
    for case_id, expected, actual in misses:
        print(f"MISS {case_id}: expected={expected}, actual={actual}")
    for case_id, expected, actual in overlay_misses:
        print(f"MISS {case_id}: expected={expected}, actual={actual}")
    return 1 if misses or overlay_misses else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, OSError, KeyError, ValueError) as error:
        print(f"devSpec validation: FAIL\n{error}", file=sys.stderr)
        sys.exit(1)
