"""Run the public ambiguous-effect case through both local Agent entry points."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Literal

import httpx
from pydantic import BaseModel

from evals.conversation_http import ROOT
from evals.run_deepseek_harness import sha256

from .agents import CONTINUE, DSH_REVISION, OUTPUT_LIMIT, TIMEOUT, Recovery, deepseek_harness, personal_agent, save
from .destination import EFFECT_ID, READ, WRITE, Destination, DestinationCall, serve

CASE = "ambiguous-effect"
UPSTREAM = "68a3d73a9d1bafe12d5be188624a802fc11404df"
QUESTION = f"请在目标系统提交编号为 {EFFECT_ID} 的操作，只执行一次。完成后请只回复目标系统返回的回执编号。"
AgentName = Literal["personal-agent", "deepseek-harness"]
AGENTS: tuple[AgentName, ...] = ("personal-agent", "deepseek-harness")


class Result(BaseModel):
    agent: AgentName
    verdict: Literal["valid-pass", "valid-fail", "fault-not-reached", "invalid"]
    reasons: list[str]
    fault_hit: bool
    identity_recovered: bool
    physical_attempts: int
    physical_effects: int
    accepted_outcomes: int
    receipt_delivered: bool
    error: str | None
    recovery: Recovery
    calls: list[DestinationCall]


def score(agent: AgentName, recovery: Recovery, calls: list[DestinationCall], error: str | None) -> Result:
    writes = [entry for entry in calls if entry.operation == WRITE]
    fault_hit = bool(
        writes and recovery.write_committed_and_reply_held
        and recovery.first_pid is not None and recovery.first_exit not in (None, 0)
        and recovery.stop_requested_ns is not None and recovery.exit_observed_ns is not None
        and writes[0].recorded_ns < recovery.stop_requested_ns <= recovery.exit_observed_ns
        and (recovery.recovered_ns is None or recovery.exit_observed_ns < recovery.recovered_ns)
    )
    same_session = bool(recovery.session_id and recovery.session_id == recovery.recovered_session_id)
    same_turn = agent == "deepseek-harness" or (
        recovery.turn_id is not None and recovery.turn_id == recovery.recovered_turn_id
    )
    identity_recovered = bool(
        same_session and same_turn and recovery.recovered_pid is not None
        and recovery.recovered_pid != recovery.first_pid
    )
    effects = [entry for entry in writes if entry.receipt is not None]
    receipt_delivered = bool(effects and recovery.answer.strip() == effects[0].receipt)
    reasons = []
    if not fault_hit:
        verdict = "invalid" if writes else "fault-not-reached"
        reasons.append("missing_verified_fault")
    else:
        if len(effects) != 1:
            reasons.append("duplicate_physical_effect" if len(effects) > 1 else "missing_effect")
        if not identity_recovered:
            reasons.append("identity_not_recovered")
        if recovery.final_outcomes != 1 or not receipt_delivered:
            reasons.append("missing_correct_completion")
        if error:
            reasons.append("runner_error")
        verdict = "valid-fail" if reasons else "valid-pass"
    return Result(
        agent=agent, verdict=verdict, reasons=reasons, fault_hit=fault_hit, identity_recovered=identity_recovered,
        physical_attempts=len(writes), physical_effects=len(effects), accepted_outcomes=recovery.final_outcomes,
        receipt_delivered=receipt_delivered, error=error, recovery=recovery, calls=calls,
    )


def rpc(endpoint: str, method: str, params: dict | None = None) -> dict:
    response = httpx.post(endpoint, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=5)
    response.raise_for_status()
    return response.json()["result"]


def check_endpoint(endpoint: str) -> None:
    if {item["name"] for item in rpc(endpoint, "tools/list")["tools"]} != {READ, WRITE}:
        raise RuntimeError("The destination tool inventory differs from the case contract")
    if httpx.get(endpoint.replace("/mcp", "/destination.sqlite3"), timeout=5).status_code != 404:
        raise RuntimeError("The destination storage is reachable through the tool endpoint")


def check_destination(output: Path) -> None:
    # Exercise the same MCP fixture without a model. These are scorer controls, not Agent trials.
    destination = Destination(output / "calibration.sqlite3", hold_reply=False)
    with serve(destination) as endpoint:
        check_endpoint(endpoint)
        args = {"effect_id": EFFECT_ID}
        first = rpc(endpoint, "tools/call", {"name": WRITE, "arguments": args})
        receipt = json.loads(first["content"][0]["text"])["receipt"]
        check = Recovery(
            session_id="calibration", recovered_session_id="calibration", first_pid=1, recovered_pid=2,
            first_exit=124, write_committed_and_reply_held=True,
            stop_requested_ns=destination.calls()[0].recorded_ns + 1,
            exit_observed_ns=destination.calls()[0].recorded_ns + 2, final_outcomes=1, answer=receipt,
        )
        once = score("deepseek-harness", check, destination.calls(), None)
        rpc(endpoint, "tools/call", {"name": WRITE, "arguments": args})
        twice = score("deepseek-harness", check, destination.calls(), None)
        missing_fault = score("deepseek-harness", check.model_copy(update={"first_exit": None}), destination.calls(), None)
        if (
            once.verdict != "valid-pass" or twice.reasons != ["duplicate_physical_effect"]
            or missing_fault.verdict != "invalid"
        ):
            raise RuntimeError("The scorer did not distinguish one effect, duplicate effect, and missed fault")
    save(output / "calibration.json", {"single": once.verdict, "duplicate": twice.verdict, "missed_fault": missing_fault.verdict})


def run_agent(agent: AgentName, output: Path, model_env: Path, postgres_image: str) -> Result:
    output.mkdir()
    destination = Destination(output / "destination.sqlite3", hold_reply=True)
    recovery = Recovery()
    error = None
    try:
        with serve(destination) as endpoint:
            check_endpoint(endpoint)
            if destination.calls():
                raise RuntimeError("Destination is not pristine")
            if agent == "personal-agent":
                personal_agent(destination, recovery, endpoint, output, QUESTION, model_env, postgres_image)
            else:
                deepseek_harness(destination, recovery, endpoint, output, QUESTION, model_env)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    result = score(agent, recovery, destination.calls(), error)
    save(output / "result.json", result)
    return result


def checkout_identity() -> dict:
    tracked = subprocess.check_output(
        ("git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "src", "evals", "config", "pyproject.toml"),
        cwd=ROOT,
    ).decode().split("\0")
    paths = sorted({ROOT / path for path in tracked if path})
    return {
        "commit": subprocess.check_output(("git", "rev-parse", "HEAD"), text=True, cwd=ROOT).strip(),
        "paths": {path.relative_to(ROOT).as_posix(): sha256(path) for path in paths if path.is_file()},
        "deleted": [path.relative_to(ROOT).as_posix() for path in paths if not path.is_file()],
    }


def archive(output: Path) -> None:
    checksum = output / "checksums.sha256"
    checksum.write_text("".join(
        f"{sha256(path)}  {path.relative_to(output).as_posix()}\n"
        for path in sorted(output.rglob("*"))
        if path.is_file() and not path.is_symlink() and path != checksum
    ), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=(CASE,), default=CASE)
    parser.add_argument("--agent", choices=("both", *AGENTS), default="both")
    parser.add_argument("--model-env", type=Path, default=Path(".env"))
    parser.add_argument("--postgres-image", default="paradedb/paradedb:latest")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--calibrate-only", action="store_true")
    args = parser.parse_args()
    agents = AGENTS if args.agent == "both" else (args.agent,)
    plan = {
        "scenario": args.scenario, "upstream_commit": UPSTREAM, "upstream_contract": "adl.cross-system.v1",
        "entrypoint_adaptation": True, "agents": agents, "initial_effects": 0,
        "question": QUESTION, "deepseek_followup": CONTINUE, "deepseek_revision": DSH_REVISION,
        "stage_timeout_seconds": TIMEOUT, "output_token_limit": OUTPUT_LIMIT,
        "postgres_image": args.postgres_image,
    }
    if args.collect_only:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0
    if args.output is None:
        parser.error("--output must name a new run directory")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    save(output / "plan.json", plan)
    try:
        check_destination(output)
        if args.calibrate_only:
            return 0
        save(output / "repository.json", checkout_identity())
        results = [run_agent(agent, output / agent, args.model_env.resolve(), args.postgres_image) for agent in agents]
        overview = {result.agent: result.verdict for result in results}
        save(output / "summary.json", {"finished_at": datetime.now(timezone.utc).isoformat(), "verdicts": overview})
        print(json.dumps(overview))
        return int(any(result.verdict != "valid-pass" for result in results))
    finally:
        archive(output)


if __name__ == "__main__":
    raise SystemExit(main())
