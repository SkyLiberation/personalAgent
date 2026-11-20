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
from uuid import uuid4

import httpx

from evals.Toolathlon import runner
from evals.Toolathlon.confirmation_probe import mapping, snapshot
from evals.Toolathlon.workspace_inputs import upload_local_workspace_attachments
from evals.conversation_http import UNVERIFIED_FLOW, effective_structured_model, submit_turn
from personal_agent.adapters.web.routes.conversation import ConversationTurnRequest, submitted_turn_id
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


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


def _record_model(output: Path, turn_id: str | None) -> dict:
    requests = []
    for path in runner.model_request_paths(output):
        request = json.loads(path.read_text(encoding="utf-8"))
        requests.append({
            "path": path.relative_to(output).as_posix(), "sha256": _digest(path),
            "operation": request["operation"],
            "actions": [action["name"] for action in request.get("action_definitions", [])],
        })
    final = runner.read_turn_trace(output, turn_id) if turn_id is not None else None
    if final is None:
        return {"requests": requests}
    facts = final.model_dump(mode="json", include={"usage", "answer_result_binding", "feature_flags_binding"})
    return {
        "requests": requests, "usage": facts["usage"],
        "answer_result": facts["answer_result_binding"], "feature_flags": facts["feature_flags_binding"],
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
    session_id = "toolathlon-" + uuid4().hex
    client_request_id = uuid4().hex
    principal = AuthenticatedPrincipal(tenant_id="personal-agent", user_id=USER)
    turn_id = submitted_turn_id(principal, session_id, client_request_id)
    report["session_id"] = session_id
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
        env = runner.product_environment(args.output, runner.postgres_url(database), servers, args.model_env)
        budget = runner.configure_interaction_budget(env, args)
        env.update(
            PERSONAL_AGENT_E2E_TRACE_DIR=str(args.output / "e2e"),
            PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR=str(args.output / "product"),
        )
        report.update(
            token_budget=budget.max_total_tokens,
            model_turn_limit=budget.max_model_turns, tool_call_limit=budget.max_tool_calls,
            evidence_class=UNVERIFIED_FLOW, release_eligible=False,
        )
        with runner.product(args.output, env) as (base, process):
            if not runner.wait_for_product(base, process, 120):
                raise RuntimeError("Product Web process exited before startup.")
            report["model"] = effective_structured_model(args.output)
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
                refs = upload_local_workspace_attachments(base, workspace, args.output, user_id=USER)
                body = ConversationTurnRequest(
                    user_id=principal.user_id, session_id=session_id, text=question,
                    client_request_id=client_request_id, create_session=True, input_artifact_refs=refs,
                )
                response = submit_turn(base, body, timeout=600)
                if response.is_success:
                    report["turn"] = response.json()
                else:
                    report["turn_error"] = {"status": response.status_code, "detail": response.json()}
    report["remote_calls"] = _record_calls(args.output)
    report["model_trace"] = _record_model(args.output, turn_id)
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
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError, httpx.HTTPError) as error:
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
