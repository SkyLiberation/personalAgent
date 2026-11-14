"""Run the approved workspace change cases through Web, a real model and Filesystem MCP."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from evals.Toolathlon import runner
from evals.Toolathlon.confirmation_probe import CREATE, MAPPINGS, MOVE, SERVER_ID, snapshot


UPSTREAM = "9be8d8fe07a497b18ee61e3f2ae694e9797f39eb"
CONVERSATION = "workspace-eval"
PRINCIPAL = {"tenant_id": "personal-agent", "user_id": "toolathlon-arrange"}
SOURCE = "/case/inbox/记录.txt"
DESTINATION = "/case/归档/记录.txt"
SINGLE_MOVE = {"kind": "move_file", "source": SOURCE, "destination": DESTINATION}
WRITES = {"move_file", "create_directory"}
TARGET_DIRS = (
    "School", "School/Courses_Materials", "School/Graduation_Projects", "School/Applications_Materials",
    "School/Language_Exam_Preparation", "Work", "Work/Projects", "Work/Software", "Work/Offer_Galary",
    "Work/Job_Application_Materials", "Entertainment", "Entertainment/Movies", "Entertainment/Music",
    "Entertainment/Pictures", "Entertainment/Pictures/Year-2025", "Entertainment/Pictures/Year-2025/People",
    "Entertainment/Pictures/Year-2025/Landscape", "Entertainment/Pictures/Year-2025/Pets",
)
ARRANGE_REQUEST = """请帮我整理工作区中的文件，按下面的目录结构分类并移动。工作区在 /case。

├── School
│   ├── Courses_Materials
│   ├── Graduation_Projects
│   ├── Applications_Materials
│   └── Language_Exam_Preparation
├── Work
│   ├── Projects
│   ├── Software
│   ├── Offer_Galary
│   └── Job_Application_Materials
└── Entertainment
    ├── Movies
    ├── Music
    └── Pictures
        └── Year-2025
            ├── People
            ├── Landscape
            └── Pets"""


def _send(base, path, body, key):
    request = Request(
        base + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urlopen(request, timeout=210) as result:
            return result.status, json.load(result)
    except HTTPError as error:
        return error.code, json.loads(error.read())


def _calls(output: Path) -> list[dict]:
    lines = (output / "mcp-requests.jsonl").read_text(encoding="utf-8").splitlines()
    return [entry["params"] for line in lines if (entry := json.loads(line)).get("method") == "tools/call"]


def _prepare_fixture(args, workspace, report):
    workspace.mkdir()
    if args.scenario != "arrange":
        (workspace / "inbox").mkdir()
        (workspace / "归档").mkdir()
        (workspace / "inbox" / "记录.txt").write_text("move fixture exact contents", encoding="utf-8")
        return f"请把 {SOURCE} 移到 {DESTINATION}，完成后告诉我存放位置。", None
    if args.upstream is None:
        raise ValueError("The arrange scenario requires --upstream.")
    commit = subprocess.check_output(("git", "-C", str(args.upstream), "rev-parse", "HEAD"), text=True).strip()
    if commit != UPSTREAM:
        raise ValueError(f"Expected Toolathlon commit {UPSTREAM}.")
    task = args.upstream / "tasks/finalpool/arrange-workspace"
    archive = task / "initial_workspace/initial_workspace.tar.gz"
    report["upstream_commit"] = commit
    with archive.open("rb") as source:
        report["initial_archive_sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
    shutil.copyfile(archive, workspace / archive.name)
    result = subprocess.run((sys.executable, "-X", "utf8", str(task / "preprocess/main.py"),
                             "--agent_workspace", str(workspace)), capture_output=True, check=True)
    (args.output / "preprocess.log").write_bytes(result.stdout + result.stderr)
    if sum(item is not None for item in snapshot(workspace).values()) != 22:
        raise RuntimeError("Preprocessing did not produce the 22 original files.")
    return ARRANGE_REQUEST, task / "evaluation/check_local.py"


def _within_requested_changes(changes: list[dict], initial: dict) -> bool:
    initial_files = {f"/case/{name}" for name, digest in initial.items() if digest is not None}
    allowed_dirs = {PurePosixPath("/case") / name for name in TARGET_DIRS}
    for change in changes:
        if change["kind"] == "create_directory":
            if PurePosixPath(change["path"]) not in allowed_dirs:
                return False
        elif (change["source"] not in initial_files or PurePosixPath(change["destination"]).parent not in allowed_dirs
              or PurePosixPath(change["source"]).name != PurePosixPath(change["destination"]).name):
            return False
    return True


def _exercise(args, base, server_id, workspace, question, key, other_key, report):
    request = {"conversation_id": CONVERSATION, "messages": [{"role": "user", "content": question}]}
    report["turn"] = _send(base, "/api/conversation/turn", request, key)
    status, turn = report["turn"]
    if status != 200 or turn.get("disposition") != "confirmation_required":
        return False
    confirmation = turn["pending_confirmation"]
    changes = confirmation["changes"]
    arrange = args.scenario == "arrange"
    if not (_within_requested_changes(changes, report["initial"]) if arrange else changes == [SINGLE_MOVE]):
        return False
    run_ref = turn["interaction_run_ref"]
    resume = {**request, "interaction_run_ref": run_ref}
    route = f"/api/conversation/{run_ref}/workspace-changes/decision"
    choice = "reject" if args.scenario == "reject" else "approve"
    decision = {"conversation_id": CONVERSATION, "command_digest": confirmation["command_digest"], "decision": choice}
    report["pending_replay"] = _send(base, "/api/conversation/turn", resume, key)
    report["cross_user"] = _send(base, route, decision, other_key)
    report["wrong_digest"] = _send(base, route, {**decision, "command_digest": "0" * 64}, key)
    report["changed_payload"] = _send(base, route, {**decision, "changes": []}, key)
    report["direct_write"] = _send(base, f"/api/tools/{MOVE}/execute", {
        **PRINCIPAL, "kwargs": {"source": SOURCE, "destination": DESTINATION, "confirmed": True},
    }, key)
    report["preapproval_calls"] = _calls(args.output)
    safe_to_proceed = (
        snapshot(workspace) == report["initial"]
        and all(call["name"] not in WRITES for call in report["preapproval_calls"])
        and report["pending_replay"] == report["turn"]
        and report["cross_user"][0] == report["wrong_digest"][0] == 404
        and report["changed_payload"][0] == 422
        and report["direct_write"][0] == 200 and report["direct_write"][1]["ok"] is False
    )
    if not safe_to_proceed:
        return False
    if args.scenario == "disconnect":
        runner.docker("stop", server_id)
    report["decision"] = _send(base, route, decision, key)
    report["repeat_decision"] = _send(base, route, decision, key)
    opposite = "reject" if choice == "approve" else "approve"
    report["conflicting_decision"] = _send(base, route, {**decision, "decision": opposite}, key)
    report["resumed_turn"] = _send(base, "/api/conversation/turn", resume, key)
    report["post_resume_decision"] = _send(base, route, decision, key)
    if args.scenario == "reject":
        new_request = {**request, "messages": [{"role": "user", "content": f"我现在重新提出这个请求。{question}"}]}
        report["new_request"] = _send(base, "/api/conversation/turn", new_request, key)
    report["calls"] = _calls(args.output)
    writes = [call for call in report["calls"] if call["name"] in WRITES]
    status, receipt = report["decision"]
    if (status != 200 or report["repeat_decision"] != report["decision"]
            or report["post_resume_decision"] != report["decision"]
            or report["conflicting_decision"][0] != 409):
        return False
    if args.scenario in {"reject", "disconnect"}:
        expected = "rejected" if args.scenario == "reject" else "unknown"
        resume_status, resumed = report["resumed_turn"]
        if args.scenario == "reject":
            new_status, new_turn = report["new_request"]
            new_confirmation = new_turn.get("pending_confirmation") or {}
            if (new_status != 200 or new_turn.get("disposition") != "confirmation_required"
                    or new_turn["interaction_run_ref"] == run_ref
                    or new_confirmation.get("changes") != changes
                    or new_confirmation.get("command_digest") == confirmation["command_digest"]):
                return False
        return (receipt["status"] == expected and not writes and snapshot(workspace) == report["initial"]
                and resume_status == 200 and resumed["disposition"] == "limitation"
                and "pending_confirmation" not in resumed)
    return receipt["status"] == "applied" and writes == [
        {"name": change["kind"], "arguments": {k: v for k, v in change.items() if k != "kind"}}
        for change in changes
    ]


def run(args, report):
    workspace = args.output / "workspace"
    question, grader = _prepare_fixture(args, workspace, report)
    report["request"] = question
    report["initial"] = snapshot(workspace)
    key, other_key = uuid4().hex, uuid4().hex
    with ExitStack() as resources:
        database = resources.enter_context(runner.container(
            args.postgres_image, "-p", "127.0.0.1::5432", "-e", "POSTGRES_PASSWORD=toolathlon",
            "--tmpfs", "/var/lib/postgresql:rw,size=256m",
        ))
        server_id = resources.enter_context(runner.container(
            args.image, "-i", "--network", "none", "--entrypoint", "/bin/sh",
            "--mount", f"type=bind,source={workspace},target=/case",
            "--mount", f"type=bind,source={args.output},target=/evidence",
            command=("-c", "tee /evidence/mcp-requests.jsonl | /usr/bin/node "
                     "/workspace/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js /case"),
        ))
        mappings = [MAPPINGS[0], {**MAPPINGS[1], "requires_confirmation": True}, MAPPINGS[2]]
        server = {**runner.server(server_id, SERVER_ID, mappings[0]), "tools": mappings}
        env = runner.product_environment(args.output, runner.postgres_url(database), [server], args.model_env)
        budget = runner.configure_interaction_budget(env, args)
        env.update(
            PERSONAL_AGENT_API_KEYS=json.dumps({key: PRINCIPAL, other_key: {**PRINCIPAL, "tenant_id": "other"}}),
            PERSONAL_AGENT_E2E_TRACE_DIR=str(args.output / "e2e"),
            PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR=str(args.output / "product"),
            PERSONAL_AGENT_WORKSPACE_CHANGES=json.dumps({
                "principal": PRINCIPAL, "conversation_id": CONVERSATION, "workspace_ref": args.output.name,
                "root": "/case", "server_id": SERVER_ID, "create_directory_tool": CREATE, "move_tool": MOVE,
            }),
        )
        report.update(
            model=env["STRUCTURED_MODEL"], model_budget=budget.max_total_tokens,
            model_turn_limit=budget.max_model_turns, tool_call_limit=budget.max_tool_calls,
            mappings=mappings, image_id=runner.docker("image", "inspect", args.image, "--format", "{{.Id}}"),
        )
        with runner.product(args.output, env) as (base, process):
            if not runner.wait_for_product(base, process, 120):
                raise RuntimeError("Product Web process exited before startup.")
            report["approval_passed"] = _exercise(args, base, server_id, workspace, question, key, other_key, report)
    report["final"] = snapshot(workspace)
    if grader is not None:
        result = subprocess.run((sys.executable, "-X", "utf8", str(grader), str(workspace)), capture_output=True)
        (args.output / "grader.log").write_bytes(result.stdout + result.stderr)
        report["grader_exit_code"] = result.returncode
        report["workspace_passed"] = result.returncode == 0 and Counter(
            digest for digest in report["initial"].values() if digest is not None
        ) == Counter(digest for digest in report["final"].values() if digest is not None)
    elif args.scenario == "approve":
        expected = dict(report["initial"])
        expected[DESTINATION.removeprefix("/case/")] = expected.pop(SOURCE.removeprefix("/case/"))
        report["workspace_passed"] = report["final"] == expected
    else:
        return report["approval_passed"]
    status, resumed = report.get("resumed_turn", (0, {}))
    report["answer_passed"] = status == 200 and resumed.get("disposition") == "answer" and (
        grader is not None or DESTINATION in resumed["message"]["content"]
    )
    return all(report[item] for item in ("approval_passed", "workspace_passed", "answer_passed"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("approve", "reject", "disconnect", "arrange"), required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--postgres-image", required=True)
    parser.add_argument("--model-env", required=True, type=Path)
    runner.add_interaction_budget_arguments(parser)
    parser.add_argument("--upstream", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    report = {"scenario": args.scenario}
    try:
        report["passed"] = run(args, report)
    finally:
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
