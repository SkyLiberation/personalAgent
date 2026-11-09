"""Probe Toolathlon Filesystem isolation and move behavior with the real Server."""

from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import ExitStack
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from personal_agent.infra.mcp import MCPError, MCPJsonRpcClient
from personal_agent.kernel.config_models import MCPServerConfig

from evals.toolathlon.runner import container, docker
from evals.toolathlon.time_case import UPSTREAM_REVISION


class FilesystemSample(TypedDict, total=False):
    scope: str
    tools: list[str]
    isolated: bool
    outside_read: str
    outside_move: str
    existing_destination_overwritten: bool
    overwrite_error: str


class FilesystemReport(TypedDict):
    toolathlon_revision: str
    image_id: str
    samples: list[FilesystemSample]


def denied(client: MCPJsonRpcClient, name: str, arguments: dict[str, str]) -> str:
    try:
        client.call_tool(name, arguments)
    except MCPError as error:
        return str(error)
    return ""


def probe(image: str, output: Path) -> FilesystemReport:
    scopes = [output / "sample-a", output / "sample-b"]
    marker = uuid4().hex
    for scope in scopes:
        scope.mkdir()
        (scope / "private.txt").write_text(f"{scope.name}-{marker}", encoding="utf-8")
    report: FilesystemReport = {
        "toolathlon_revision": UPSTREAM_REVISION,
        "image_id": docker("image", "inspect", image, "--format", "{{.Id}}"),
        "samples": [],
    }
    for scope in scopes:
        with ExitStack() as resources:
            container_id = resources.enter_context(container(
                image, "-i", "--network", "none", "--entrypoint", "/usr/bin/node",
                "--mount", f"type=bind,source={scope},target=/case",
                command=("/workspace/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js", "/case"),
            ))
            client = MCPJsonRpcClient(MCPServerConfig(
                server_id="toolathlon-filesystem",
                transport="stdio",
                command="docker",
                args=("start", "-ai", container_id),
            ))
            resources.callback(client.close)
            discovered = [tool.name for tool in client.list_tools()]
            read = client.call_tool("read_file", {"path": "/case/private.txt"})
            cross_read = denied(client, "read_file", {"path": "/other-sample/private.txt"})
            cross_move = denied(client, "move_file", {
                "source": "/case/private.txt", "destination": "/other-sample/private.txt",
            })
            original = f"{scope.name}-{marker}"
            isolated = (
                original in json.dumps(read)
                and "outside allowed directories" in cross_read
                and "outside allowed directories" in cross_move
                and (scope / "private.txt").read_text(encoding="utf-8") == original
            )
            sample: FilesystemSample = {
                "scope": scope.name, "tools": discovered, "isolated": isolated,
                "outside_read": cross_read, "outside_move": cross_move,
            }
            if scope == scopes[0]:
                (scope / "destination.txt").write_text("existing destination", encoding="utf-8")
                overwrite_error = denied(client, "move_file", {
                    "source": "/case/private.txt", "destination": "/case/destination.txt",
                })
                sample["existing_destination_overwritten"] = (
                    (scope / "destination.txt").read_text(encoding="utf-8") == original
                )
                sample["overwrite_error"] = overwrite_error
            report["samples"].append(sample)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    report = probe(args.image, output)
    path = output / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "report.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "\n")
    print(path)
    return 0 if all(sample["isolated"] for sample in report["samples"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
