"""Verify the tool policy gate through the Web API and a real Filesystem MCP Server."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from contextlib import ExitStack
from pathlib import Path
from typing import Any, TypedDict

from evals.Toolathlon.runner import container, docker, postgres_url, product, product_environment, request, wait_for_product


SERVER_ID = "toolathlon-filesystem"
USER_ID = "toolathlon-arrange"
MOVE = "filesystem.move_file"
CREATE = "filesystem.create_directory"
LIST = "filesystem.list_directory"
MOVE_ARGS = {"source": "/case/source.txt", "destination": "/case/destination.txt"}
PROBE_CALLS = (
    ("unconfirmed", MOVE, MOVE_ARGS),
    ("claimed_confirmation", MOVE, {**MOVE_ARGS, "confirmed": True}),
    ("denied_scope", CREATE, {"path": "/case/forbidden"}),
    ("allowed_read", LIST, {"path": "/case"}),
)


class ProbeReport(TypedDict, total=False):
    head: str
    passed: bool
    image_id: str
    postgres_image_id: str
    tracked_diff_sha256: str
    probe_sha256: str
    tool_mappings: list[dict[str, object]]
    denied_scope: str
    requests: dict[str, dict[str, str | bool]]
    responses: dict[str, dict[str, Any]]
    remote_tools: list[str]
    decisions: list[dict[str, Any]]
    attempts: list[int]
    confirmed_audit: list[bool]
    error_kinds: list[str | None]
    workspace_unchanged: bool
    environment_error: str


def mapping(remote: str, name: str, operation: str, effect: str, **settings: object) -> dict[str, object]:
    return {
        "remote_name": remote, "name": name, "operations": [operation],
        "semantic_domains": ["workspace"], "resource_types": ["file"],
        "trust_level": "scoped", "credential_mode": "none", "data_egress_class": "none",
        "attestation_status": "pinned", "freshness_profile": "realtime",
        "output_contract": "workspace_operation", "evidence_contract": "provider_output",
        "failure_semantics": "typed_failure", "permission_scope": f"toolathlon:{operation}",
        "side_effects": [effect], "max_retries": 0, **settings,
    }


MAPPINGS = [
    mapping("move_file", MOVE, "update", "write_local",
            side_effects=["write_local", "irreversible"], risk_level="high", requires_confirmation=True),
    mapping("create_directory", CREATE, "create", "write_local"),
    mapping("list_directory", LIST, "list", "read_local"),
]


def snapshot(workspace: Path) -> dict[str, str | None]:
    return {
        path.relative_to(workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        for path in sorted(workspace.rglob("*"))
    }


def run(args: argparse.Namespace, report: ProbeReport) -> None:
    output = args.output
    workspace = output / "workspace"
    workspace.mkdir()
    (workspace / "source.txt").write_text("confirmation probe", encoding="utf-8")
    before = snapshot(workspace)
    with ExitStack() as resources:
        database = resources.enter_context(container(
            args.postgres_image, "-p", "127.0.0.1::5432", "-e", "POSTGRES_PASSWORD=toolathlon",
            "--tmpfs", "/var/lib/postgresql:rw,size=256m",
        ))
        server = resources.enter_context(container(
            args.image, "-i", "--network", "none", "--entrypoint", "/bin/sh",
            "--mount", f"type=bind,source={workspace},target=/case,readonly",
            "--mount", f"type=bind,source={output},target=/evidence",
            command=("-c", "tee /evidence/mcp-requests.jsonl | /usr/bin/node "
                     "/workspace/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js /case"),
        ))
        env = product_environment(output, postgres_url(database), [{
            "server_id": SERVER_ID, "transport": "stdio", "command": "docker",
            "args": ["start", "-ai", server], "tools": MAPPINGS,
        }], None)
        env.update(
            PERSONAL_AGENT_POLICY_DENY_SCOPES="toolathlon:create",
            PERSONAL_AGENT_GRAPHITI_URI="bolt://127.0.0.1:1",
            PERSONAL_AGENT_E2E_TRACE_DIR=str(output / "e2e"),
            PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR=str(output / "product"),
            PYTHONDONTWRITEBYTECODE="1",
        )
        with product(output, env) as (base, process):
            if not wait_for_product(base, process, 45):
                raise RuntimeError("Product Web process exited before startup")
            report["responses"] = {
                label: request(base, f"/api/tools/{name}/execute", {
                    "tenant_id": "personal-agent", "user_id": USER_ID, "kwargs": arguments,
                }, timeout=35)
                for label, name, arguments in PROBE_CALLS
            }

    incoming = [json.loads(line) for line in (output / "mcp-requests.jsonl").read_text(encoding="utf-8").splitlines()]
    report["remote_tools"] = [entry["params"]["name"] for entry in incoming if entry.get("method") == "tools/call"]
    log = (output / "web.log").read_text(encoding="utf-8").splitlines()
    report["decisions"] = [json.loads(line.split(" | policy.decision | ", 1)[1])
                           for line in log if " | policy.decision | " in line]
    audits = [json.loads(line.split(" | tool.audit | ", 1)[1])
              for line in log if " | tool.audit | " in line]
    report["attempts"] = [item["attempts"] for item in audits]
    report["confirmed_audit"] = [item["confirmed"] for item in audits]
    report["error_kinds"] = [item["output"].get("error_kind") for item in audits]
    report["workspace_unchanged"] = snapshot(workspace) == before
    responses = report["responses"]
    report["passed"] = (
        report["remote_tools"] == ["list_directory"]
        and [(item["tool_name"], item["effect"], item["rule"]) for item in report["decisions"]
             if item["action"] == "tool_call"] == [
            (MOVE, "require_confirmation", "tool.high_risk_confirmation"),
            (MOVE, "require_confirmation", "tool.high_risk_confirmation"),
            (CREATE, "deny", "override.deny_scope"),
            (LIST, "allow", "tool.default"),
        ]
        and report["attempts"] == [0, 0, 0, 1]
        and report["confirmed_audit"] == [False, False, False, False]
        and report["error_kinds"] == ["permission", "permission", "permission", None]
        and all(responses[label]["ok"] is False for label in ("unconfirmed", "claimed_confirmation", "denied_scope"))
        and responses["allowed_read"]["ok"]
        and "source.txt" in json.dumps(responses["allowed_read"]["data"])
        and report["workspace_unchanged"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--postgres-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    report: ProbeReport = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(), "passed": False}
    try:
        report.update(
            image_id=docker("image", "inspect", args.image, "--format", "{{.Id}}"),
            postgres_image_id=docker("image", "inspect", args.postgres_image, "--format", "{{.Id}}"),
            tracked_diff_sha256=hashlib.sha256(subprocess.check_output(["git", "diff", "--binary", "HEAD"])).hexdigest(),
            probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            tool_mappings=MAPPINGS, denied_scope="toolathlon:create",
            requests={label: arguments for label, _, arguments in PROBE_CALLS},
        )
        run(args, report)
    except Exception as error:
        report["environment_error"] = f"{type(error).__name__}: {error}"
    data = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    (args.output / "report.json").write_bytes(data)
    (args.output / "report.sha256").write_text(hashlib.sha256(data).hexdigest() + "\n", encoding="ascii")
    print(f"{args.output / 'report.json'} [{report['passed']}]")
    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
