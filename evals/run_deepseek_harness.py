"""Run one dataset prompt against the shared, source-built DeepSeek Harness."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from hashlib import file_digest
from pathlib import Path
from time import monotonic, sleep
from typing import TypedDict
from uuid import uuid4


CHECKOUT = Path(__file__).resolve().parent / "agents" / "deepseek-harness"
RUNTIME = CHECKOUT / "packages/examples/jsonrpc-demo/lib/bin.js"
SDK_SOURCE = CHECKOUT / "python/sdk/src"


class HarnessReport(TypedDict):
    harness_revision: str
    runtime_sha256: str
    provider: str
    model: str
    max_tokens: int | None
    timeout_seconds: int
    prompt_sha256: str
    cordis_sha256: str
    session_id: str
    finish_reason: str | None
    error_type: str | None


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--cordis", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-tokens", type=positive_int)
    parser.add_argument("--timeout-seconds", type=positive_int, default=1200)
    args = parser.parse_args()

    node = shutil.which("node")
    if node is None or not RUNTIME.is_file() or not SDK_SOURCE.is_dir():
        parser.error("Build the shared checkout as described in evals/deepseek-harness-deployment.md")
    revision = subprocess.check_output(
        ("git", "-C", str(CHECKOUT), "rev-parse", "HEAD"), text=True,
    ).strip()
    workspace = args.workspace.resolve()
    output = args.output.resolve()
    if not workspace.is_dir() or output.is_relative_to(workspace):
        parser.error("Provide an existing task workspace and an output directory outside it")

    prompt = args.prompt_file.read_text(encoding="utf-8")
    cordis = args.cordis.resolve()
    report: HarnessReport = {
        "harness_revision": revision, "runtime_sha256": sha256(RUNTIME),
        "provider": args.provider, "model": args.model,
        "max_tokens": args.max_tokens, "timeout_seconds": args.timeout_seconds,
        "prompt_sha256": sha256(args.prompt_file), "cordis_sha256": sha256(cordis),
        "session_id": uuid4().hex, "finish_reason": None, "error_type": None,
    }
    session_root = output / "sessions"

    sys.path.insert(0, str(SDK_SOURCE))
    from deepseek_harness import DeepSeekHarness
    from deepseek_harness.api import final_response, finish_reason, normalize_input

    harness = DeepSeekHarness(
        cwd=str(workspace), runtime_cwd=str(workspace), cordis=str(cordis),
        session_root=str(session_root), provider=args.provider, model=args.model,
        max_tokens=args.max_tokens, request_timeout_seconds=args.timeout_seconds,
        launch_args_override=(node, str(RUNTIME)), env={"DSH_HOME": str(output / "dsh-home")},
    )
    output.mkdir(parents=True, exist_ok=False)
    try:
        deadline = monotonic() + args.timeout_seconds
        harness.start()
        harness.client.session_prompt(report["session_id"], normalize_input(prompt))
        while monotonic() < deadline:
            path = next(session_root.glob(f"*/{report['session_id']}/session.jsonl"), None)
            if path is not None:
                complete_lines = path.read_bytes().rpartition(b"\n")[0].splitlines()
                events = [json.loads(line) for line in complete_lines]
                if (reason := finish_reason(events)) is not None:
                    report["finish_reason"] = reason
                    (output / "final-response.txt").write_bytes(final_response(events).encode("utf-8"))
                    break
            sleep(0.5)
        else:
            raise TimeoutError("No persisted Harness terminal event before the deadline")
    except Exception as error:
        report["error_type"] = type(error).__name__
        raise
    finally:
        harness.close()
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        artifacts = [output / "report.json", output / "final-response.txt", *session_root.rglob("*")]
        (output / "checksums.sha256").write_text(
            "".join(f"{sha256(path)}  {path.relative_to(output).as_posix()}\n"
                    for path in sorted(artifacts) if path.is_file()),
            encoding="utf-8",
        )
    return int(report["finish_reason"] != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
