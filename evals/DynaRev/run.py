"""Run a selected public DynaRev case through both Agent entry points."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import subprocess
import sys
from time import monotonic
from urllib.parse import urlsplit

from dotenv import dotenv_values
from openai import OpenAI

from evals.conversation_http import ROOT
from evals.run_deepseek_harness import sha256

UPSTREAM = "f541cf529269d81f1105d767cad55a317d5be3d3"
AGENTS = ("personal-agent", "deepseek-harness")
JUDGE_MIN_OUTPUT = 2048


@dataclass(frozen=True)
class CaseSource:
    filename: str
    instance_id: str


CASES = {
    "cruise-steering": CaseSource("additive.jsonl", "dyna_0a0fa834ce41b5297c6474293383759d_110325"),
    "apple-model-override": CaseSource("unconditional_override.jsonl", "dyna_d71be72aa25c3eab8eea47a0e60382e2"),
    "akc-conditional-override": CaseSource("conditional_override.jsonl", "dyna_eb2db4b769c145dbe6ba4f74f3e0de98"),
}


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(("git", *args), cwd=cwd).decode("utf-8").strip()


def source_line(dataset: Path, instance_id: str) -> bytes:
    with dataset.open("rb") as stream:
        return next(line for line in stream if line.strip() and json.loads(line)["instance_id"] == instance_id)


def code_identity() -> dict:
    paths = git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "src", "evals", "config")
    return {"commit": git("rev-parse", "HEAD"), "paths": {
        path: sha256(ROOT / path) if (ROOT / path).is_file() else None
        for path in sorted(set(paths.split("\0"))) if path
    }}


def archive(output: Path) -> None:
    checksum = output / "checksums.sha256"
    checksum.write_text("".join(
        f"{sha256(path)}  {path.relative_to(output).as_posix()}\n"
        for path in sorted(output.rglob("*"))
        if path.is_file() and not path.is_symlink() and path != checksum
    ), encoding="utf-8")


@contextmanager
def judge_client(values, timeout: int):
    with OpenAI(base_url=values["STRUCTURED_BASE_URL"], api_key=values["STRUCTURED_API_KEY"],
                max_retries=0, timeout=timeout) as client:
        if values["STRUCTURED_MODEL"] == "MiniMax-M3.1-Flash":
            upstream_create = client.chat.completions.create

            def complete(**kwargs):
                kwargs["max_tokens"] = max(kwargs.get("max_tokens", 0), JUDGE_MIN_OUTPUT)
                kwargs["reasoning_effort"] = "low"
                return upstream_create(**kwargs)

            client.chat.completions.create = complete
        yield client


def run_agent(agent, task, output: Path, model_env: Path, values, postgres_image: str,
              completion_fallback: bool) -> dict:
    from .agents import Terminal, deepseek_harness, personal_agent
    from .browser import BrowserEpisode, serve, write_json

    output.mkdir()
    started = monotonic()
    with judge_client(values, timeout=25) as judge:
        episode = BrowserEpisode(task, output, judge, values["STRUCTURED_MODEL"])
        terminal = Terminal(reason="not_started")
        outcome = "completed"
        try:
            with serve(episode, completion_fallback=completion_fallback) as endpoint:
                try:
                    if agent == "personal-agent":
                        terminal = personal_agent(episode, endpoint, model_env, postgres_image)
                    else:
                        terminal = deepseek_harness(episode, endpoint, values)
                except Exception as error:
                    terminal = Terminal(reason=f"{type(error).__name__}: {error}")
                episode.finish(terminal.answer, terminal.completed)
        except Exception as error:
            terminal = Terminal(reason=f"{type(error).__name__}: {error}")
            outcome = "environment_error"
        if episode.error:
            outcome = "environment_error"
        elif any(not attempt["accepted"] for attempt in episode.attempts):
            outcome = "steering_rejected"
        elif outcome == "completed" and not terminal.completed:
            outcome = "no_final_answer"
        elif outcome == "completed" and len(episode.delivered) != len(task.revisions):
            outcome = "milestone_not_reached"
        report = {"agent": agent, "outcome": outcome, "delivered": episode.delivered,
                  "steering": episode.attempts, "browser_error": episode.error,
                  "terminal": terminal.model_dump(), "elapsed_seconds": round(monotonic() - started, 2)}
        write_json(output / "result.json", report)
        return report


def grade(report: dict, task, output: Path, values, execution_date: str) -> dict:
    from src.evaluator_lib import TaskEvaluator
    from src.utils.log_reader import LogReader

    from .browser import write_json

    report["score"] = None
    if report["outcome"] != "environment_error" and report["terminal"]["completed"]:
        try:
            with judge_client(values, timeout=50) as judge:
                report["score"] = TaskEvaluator(
                    task, LogReader(output, task.instance_id), judge, values["STRUCTURED_MODEL"], execution_date,
                ).evaluate()
        except Exception as error:
            report["grader_error"] = f"{type(error).__name__}: {error}"
    score = report["score"]
    report["passed"] = report["outcome"] == "completed" and score is not None and score["is_correct"]
    write_json(output / "result.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True, help="DynaRev source checkout at the pinned revision")
    parser.add_argument("--case", choices=CASES, default="cruise-steering", help="public case to run (default: %(default)s)")
    parser.add_argument("--output", type=Path, help="new archive directory")
    parser.add_argument("--model-env", type=Path, default=Path(".env"))
    parser.add_argument("--postgres-image", default="paradedb/paradedb:latest")
    parser.add_argument("--execution-date", default=date.today().isoformat())
    parser.add_argument("--agent", choices=("both", *AGENTS), default="both")
    parser.add_argument("--upstream-completion-fallback", action="store_true",
                        help="send the next pending revision before a premature turn close")
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    agents = AGENTS if args.agent == "both" else (args.agent,)
    upstream = args.upstream.resolve()
    if git("rev-parse", "HEAD", cwd=upstream) != UPSTREAM or git("status", "--porcelain", cwd=upstream):
        parser.error(f"Provide a clean DynaRev checkout at {UPSTREAM}")
    sys.path.insert(0, str(upstream))
    from src.agent_lib.data import load_dyna_jsonl

    case = CASES[args.case]
    dataset = upstream / "data" / case.filename
    task = next((item for item in load_dyna_jsonl(dataset) if item.instance_id == case.instance_id), None)
    if task is None:
        parser.error(f"Case {case.instance_id} is missing from {dataset}")
    plan = {"case": args.case, "task": task.instance_id, "upstream_commit": UPSTREAM,
            "agents": agents, "repeats_per_agent": 1,
            "revision_delivery": "upstream" if args.upstream_completion_fallback else "milestone_only",
            "execution_date": args.execution_date, "upstream_dataset": dataset.relative_to(upstream).as_posix(),
            "upstream_dataset_sha256": sha256(dataset), "runtime": task.runtime}
    if args.collect_only:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if args.output is None:
        parser.error("--output must name a new run directory")
    values = dotenv_values(args.model_env)
    if any(not values.get(key) for key in ("STRUCTURED_API_KEY", "STRUCTURED_BASE_URL", "STRUCTURED_MODEL")):
        parser.error("--model-env needs the structured model endpoint, name and credential")

    from .agents import DSH_REVISION, OUTPUT_LIMIT, TIMEOUT
    from .browser import write_json

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "case.jsonl").write_bytes(source_line(dataset, task.instance_id))
    write_json(output / "plan.json", {
        **plan, "harness_commit": DSH_REVISION, "timeout_seconds": TIMEOUT, "max_output_tokens": OUTPUT_LIMIT,
        "provider": urlsplit(values["STRUCTURED_BASE_URL"]).hostname, "model": values["STRUCTURED_MODEL"],
        "judge_options": ({"min_output_tokens": JUDGE_MIN_OUTPUT, "reasoning_effort": "low"}
                          if values["STRUCTURED_MODEL"] == "MiniMax-M3.1-Flash" else "upstream_defaults"),
        "trial_kind": "product_steering_adaptation",
    })
    write_json(output / "repository.json", code_identity())
    try:
        with ProcessPoolExecutor(max_workers=len(agents)) as workers:
            futures = [workers.submit(run_agent, agent, task, output / agent, args.model_env.resolve(), values,
                                      args.postgres_image, args.upstream_completion_fallback) for agent in agents]
            reports = [future.result() for future in futures]
        for report in reports:
            grade(report, task, output / report["agent"], values, args.execution_date)
        write_json(output / "summary.json", reports)
        print(json.dumps([{key: report[key] for key in ("agent", "outcome", "passed", "delivered")}
                          for report in reports], ensure_ascii=False))
        return int(not all(report["passed"] for report in reports))
    finally:
        archive(output)


if __name__ == "__main__":
    raise SystemExit(main())
