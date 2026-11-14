"""Run pinned Toolathlon PDF cases with independent upstream file grading."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
from urllib.error import HTTPError

from evals.Toolathlon import runner
from evals.Toolathlon.confirmation_probe import mapping, snapshot


REVISION = "9be8d8fe07a497b18ee61e3f2ae694e9797f39eb"
PDF_IMAGE = "lockon0927/toolathlon-task-image@sha256:4d04fe4e0a6fdb4946f51bb05120cb44a0eef980231c11252f93b62897afcb9f"
FILE_IMAGE = "personal-agent-toolathlon-filesystem:2.2.0"
PDF_VERSION = "0.1.4"
USER = "toolathlon-pdf"


@dataclass(frozen=True)
class Case:
    prompt: str
    output: str
    grader: str
    grader_function: str
    text_reader: str


CASES = {
    "imagenet": Case("task_cn.md", "survey.tex", "check_local.py", "check_local", "read_multiple_files"),
    "detect-revised-terms": Case(
        "task.md", "revised_terms.csv", "check_content.py", "check_content", "read_text_file",
    ),
}
PDF_TOOLS = (
    "get_pdf_info", "read_pdf_pages", "search_pdf_content",
    "search_pdf_next_page", "search_pdf_prev_page", "search_pdf_go_page", "search_pdf_info",
)


def _digest(path: Path) -> str:
    with path.open("rb") as data:
        return hashlib.file_digest(data, "sha256").hexdigest()


def _tool(base: str, name: str, arguments: dict) -> dict:
    return runner.request(base, f"/api/tools/{name}/execute", {
        "tenant_id": "personal-agent", "user_id": USER, "kwargs": arguments,
    }, timeout=80)


def _stdio_servers(
    resources: ExitStack, workspace: Path, output: Path, wrapper: Path, evidence: Path, *, text_reader: str,
) -> list[dict]:
    source_mount = f"type=bind,source={workspace},target=/case,readonly"
    logs = f"type=bind,source={evidence},target=/evidence"
    files = resources.enter_context(runner.container(
        FILE_IMAGE, "-i", "--network", "none", "--entrypoint", "/bin/sh",
        "--mount", source_mount, "--mount", f"type=bind,source={output},target=/out", "--mount", logs,
        command=("-c", "tee /evidence/filesystem-requests.jsonl | /usr/bin/node "
                 "/workspace/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js /case /out"),
    ))
    pdf = resources.enter_context(runner.container(
        PDF_IMAGE, "-i", "--network", "none", "--entrypoint", "/bin/sh",
        "--mount", source_mount, "--mount", logs, "--workdir", "/case",
        "--mount", f"type=bind,source={wrapper},target=/pdf-tools-wrapper.py,readonly",
        command=("-c", f"tee /evidence/pdf-requests.jsonl | uv tool run --offline --from pdf-tools-mcp=={PDF_VERSION} "
                 "python /pdf-tools-wrapper.py --workspace_path /case --tempfile_dir /tmp/toolathlon-pdf"),
    ))
    files_mapped = [
        mapping("list_directory", "filesystem.list_directory", "list", "read_local"),
        mapping(text_reader, f"filesystem.{text_reader}", "read", "read_local"),
        mapping("write_file", "filesystem.write_file", "create", "write_local",
                risk_level="medium", description="将完整文本写入本次任务的独立 /out 输出目录。/case 原件为只读。"),
    ]
    pdf_mapped = [mapping(name, f"pdf.{name}", "read", "read_local", timeout_seconds=120) for name in PDF_TOOLS]
    return [
        {**runner.server(files, "toolathlon-filesystem", files_mapped[0]), "tools": files_mapped},
        {**runner.server(pdf, "toolathlon-pdf", pdf_mapped[0]), "tools": pdf_mapped},
    ]


def _record_calls(output: Path) -> dict[str, dict[str, int]]:
    totals = {}
    for server in ("filesystem", "pdf"):
        path = output / f"{server}-requests.jsonl"
        if path.exists():
            calls = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
            totals[server] = dict(Counter(call["params"]["name"] for call in calls if call.get("method") == "tools/call"))
    return totals


def _record_model(output: Path) -> dict:
    runs = output / "product-data/interaction_runs"
    requests = []
    for path in runner.model_request_paths(output):
        request = json.loads(path.read_text(encoding="utf-8"))
        requests.append({
            "path": path.relative_to(output).as_posix(), "sha256": _digest(path),
            "operation": request["operation"],
            "actions": [action["name"] for action in request.get("action_definitions", [])],
        })
    revisions = sorted(runs.glob("*/[0-9][0-9][0-9][0-9].json"))
    if not revisions:
        return {"requests": requests}
    final = json.loads(revisions[-1].read_text(encoding="utf-8"))
    return {
        "requests": requests, "usage": final["usage"],
        "answer_result": final["answer_result_binding"], "feature_flags": final["feature_flags_binding"],
    }


def _grade(upstream: Path, task: Path, case: Case, output: Path) -> dict:
    if case.grader_function == "check_local":
        functions = runpy.run_path(str(task / "evaluation" / case.grader))
        passed, error = functions[case.grader_function](str(output), str(task / "groundtruth_workspace"))
        return {"passed": bool(passed), "detail": error}
    script = '''
import importlib.util
import json
import runpy
import sys

config = importlib.util.spec_from_file_location(
    "configs.global_configs", "/eval/configs/global_configs_example.py",
)
module = importlib.util.module_from_spec(config)
sys.modules[config.name] = module
config.loader.exec_module(module)
task = sys.argv[1]
grader = runpy.run_path(task + "/evaluation/check_content.py")["check_content"]
passed, detail = grader("/out", task + "/groundtruth_workspace")
print(json.dumps({"passed": bool(passed), "detail": detail}))
'''
    result = runner.docker(
        "run", "--rm", "--network", "none", "--entrypoint", "/workspace/.venv/bin/python",
        "-e", "PYTHONPATH=/eval", "--mount", f"type=bind,source={upstream},target=/eval,readonly",
        "--mount", f"type=bind,source={output},target=/out,readonly",
        PDF_IMAGE, "-c", script, f"/eval/tasks/finalpool/{task.name}",
    )
    return json.loads(result.splitlines()[-1])

def _run(args, report: dict) -> bool:
    case = CASES[args.scenario]
    task = args.upstream / "tasks/finalpool" / args.scenario
    revision = subprocess.check_output(("git", "-C", str(args.upstream), "rev-parse", "HEAD"), text=True).strip()
    if revision != REVISION:
        raise ValueError(f"Expected Toolathlon revision {REVISION}.")
    workspace = args.output / "input"
    deliverables = args.output / "deliverables"
    shutil.copytree(task / "initial_workspace", workspace)
    deliverables.mkdir()
    question = (task / "docs" / case.prompt).read_text(encoding="utf-8").strip()
    question += f"\n\n本次环境的原件在 /case。请将交付文件保存为 /out/{case.output}。"
    initial = snapshot(workspace)
    report.update(
        upstream_revision=revision, request=question, initial=initial,
        source_revision=subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip(),
        source_diff_sha256=hashlib.sha256(subprocess.check_output(("git", "diff", "--binary", "HEAD"))).hexdigest(),
        runner_sha256=_digest(Path(__file__)),
        grader_sha256=_digest(task / "evaluation" / case.grader),
        pdf_image=PDF_IMAGE, pdf_version=PDF_VERSION,
        filesystem_image=runner.docker("image", "inspect", FILE_IMAGE, "--format", "{{.Id}}"),
    )
    with ExitStack() as resources:
        database = resources.enter_context(runner.container(
            args.postgres_image, "-p", "127.0.0.1::5432", "-e", "POSTGRES_PASSWORD=toolathlon",
            "--tmpfs", "/var/lib/postgresql:rw,size=256m",
        ))
        wrapper = args.upstream / "utils/local_servers/pdf_tools_local_wrapper.py"
        report["pdf_wrapper_sha256"] = _digest(wrapper)
        servers = _stdio_servers(
            resources, workspace, deliverables, wrapper, args.output, text_reader=case.text_reader,
        )
        report["mappings"] = {server["server_id"]: server["tools"] for server in servers}
        env = runner.product_environment(
            args.output, runner.postgres_url(database), servers, args.model_env,
            feature_flags=runner.FeatureFlags(goal_verification=False, answer_verification=False),
        )
        budget = runner.configure_interaction_budget(env, args)
        env.update(
            PERSONAL_AGENT_ANSWER_RESULT='{"writer":"direct"}',
            PERSONAL_AGENT_E2E_TRACE_DIR=str(args.output / "e2e"),
            PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR=str(args.output / "product"),
        )
        report.update(
            model=env["STRUCTURED_MODEL"], token_budget=budget.max_total_tokens,
            model_turn_limit=budget.max_model_turns, tool_call_limit=budget.max_tool_calls,
        )
        with runner.product(args.output, env) as (base, process):
            if not runner.wait_for_product(base, process, 120):
                raise RuntimeError("Product Web process exited before startup.")
            sample = next(iter(sorted(workspace.glob("*.pdf"))))
            report["pdf_preflight"] = _tool(base, "pdf.read_pdf_pages", {
                "pdf_file_path": f"/case/{sample.name}", "start_page": 1, "end_page": 1,
            })
            report["readonly_preflight"] = _tool(base, "filesystem.write_file", {
                "path": "/case/toolathlon-readonly-probe.txt", "content": "readonly boundary probe",
            })
            report["preflight_passed"] = (
                report["pdf_preflight"]["ok"] is True and report["readonly_preflight"]["ok"] is False
                and snapshot(workspace) == initial and snapshot(deliverables) == {}
            )
            if report["preflight_passed"]:
                try:
                    report["turn"] = runner.request(base, "/api/conversation/turn", {
                        "user_id": USER, "conversation_id": "toolathlon-" + args.scenario,
                        "messages": [{"role": "user", "content": question}],
                    }, timeout=600)
                except HTTPError as error:
                    report["turn_error"] = {"status": error.code, "detail": json.load(error)}
    report["remote_calls"] = _record_calls(args.output)
    report["model_trace"] = _record_model(args.output)
    report["input_unchanged"] = snapshot(workspace) == initial
    report["deliverables"] = snapshot(deliverables)
    report["grader"] = _grade(args.upstream, task, case, deliverables)
    return bool(
        report["preflight_passed"] and report["input_unchanged"] and set(report["deliverables"]) == {case.output}
        and report.get("turn", {}).get("disposition") == "answer" and report["grader"]["passed"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=tuple(CASES), required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--model-env", type=Path, required=True)
    runner.add_interaction_budget_arguments(parser)
    parser.add_argument("--postgres-image", default="paradedb/paradedb:latest")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.upstream = args.upstream.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    report = {"scenario": args.scenario}
    try:
        report["passed"] = _run(args, report)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        report.update(passed=False, environment_error=f"{type(error).__name__}: {error}")
    finally:
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        files = sorted(path for path in args.output.iterdir() if path.is_file())
        (args.output / "checksums.sha256").write_text(
            "".join(f"{_digest(path)}  {path.name}\n" for path in files), encoding="utf-8",
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
