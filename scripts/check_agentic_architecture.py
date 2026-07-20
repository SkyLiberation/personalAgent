"""Fail-closed static gates for the agentic decision/control boundary."""

from __future__ import annotations

import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_FUNCTIONS = {
    "_compile_contract_plan",
    "_materialize_contract_action",
    "_procedure_decision",
    "_default_step_answer",
    "_apply_tool_result_to_state",
    "_apply_declared_result_to_state",
}


def _attribute_path(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def main() -> int:
    failures: list[str] = []
    for path in (ROOT / "src" / "personal_agent").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in FORBIDDEN_FUNCTIONS:
                    failures.append(f"{relative}:{node.lineno}: forbidden business fallback {node.name}")
            if relative.endswith("orchestration/orchestration_nodes/_steps.py") and isinstance(
                node, (ast.Assign, ast.AnnAssign, ast.AugAssign),
            ):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if _attribute_path(target) == "state.answer":
                        failures.append(
                            f"{relative}:{node.lineno}: Tool/step adapter cannot write state.answer"
                        )
            if (
                relative.endswith("governance/decision_admission.py")
                and isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "model_copy"
            ):
                failures.append(
                    f"{relative}:{node.lineno}: Admission cannot repair a Proposal with model_copy"
                )
    obsolete = ROOT / "src" / "personal_agent" / "runtime" / "direct.py"
    if obsolete.exists():
        failures.append("src/personal_agent/runtime/direct.py: deterministic direct-answer path is forbidden")
    forbidden_paths = (
        ROOT / "evals" / "resolver_quality" / "scorer.py",
        ROOT / "evals" / "orchestration_quality" / "cases.json",
    )
    for path in forbidden_paths:
        if path.exists():
            failures.append(f"{path.relative_to(ROOT).as_posix()}: obsolete soft-score gate is forbidden")
    analyzer_source = (
        ROOT / "src" / "personal_agent" / "planning" / "task_analyzer.py"
    ).read_text(encoding="utf-8")
    if "TaskAnalysisOutput" in analyzer_source:
        failures.append("task analyzer cannot restore the pre-admission TaskAnalysisOutput DTO")
    capability_contract = (
        ROOT / "src" / "personal_agent" / "capabilities" / "contracts" / "execution.py"
    ).read_text(encoding="utf-8")
    if "execution_grant: ExecutionGrant" in capability_contract:
        failures.append("capability resolution cannot own execution grant issuance")
    resolver_source = (
        ROOT / "src" / "personal_agent" / "capabilities" / "resolver.py"
    ).read_text(encoding="utf-8")
    if "capabilities.contracts.grants" in resolver_source or "_grant_for" in resolver_source:
        failures.append("capability resolver cannot issue grants before final command binding")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Agentic architecture gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
