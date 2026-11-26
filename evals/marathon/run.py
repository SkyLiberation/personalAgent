"""Run the published CTXAgent marathon:0 with PersonalAgent and DeepSeek Harness."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
from time import monotonic
from uuid import uuid4

from dotenv import dotenv_values
from pydantic import BaseModel, Field, model_validator

from evals.deepseek_runtime import VERSION as DSH_VERSION
from evals.longDS.longds_materials import seal, verify_seal
from evals.longDS.run_longds import _source_identity
from evals.longDS.run_longds_harness import write_record
from evals.run_deepseek_harness import CHECKOUT, sha256
from evals.Toolathlon.runner import container, docker
from .agents import (
    TASK_TOKENS,
    TURN_TIMEOUT,
    WINDOW,
    Delivery,
    extract_host_workspace,
    harness,
    harness_usage,
    personal,
)


UPSTREAM_REVISION = "77ec7a9e9127e3258b035af32dc7f13730979902"
POLYGLOT_REVISION = "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"
SCICODE_REVISION = "e3158ea011d4235245a547460d3688d7ccbf9900"
LETTA_REVISION = "e6140262abf970b7ea94bcac548b52a9dd7a7e2b"
H5_SHA256 = "48b0272a88b17dbd29777c217e1b4fb2b019b92e11cc2add847409db9541b890"
HERE = Path(__file__).resolve().parent
DEFAULT_IMAGE = "personal-agent-marathon:go127-node22"
WORK_VOLUME = "/workspace/marathon"


class Turn(BaseModel):
    number: int = Field(ge=1, le=212)
    kind: str
    prompt: str = Field(min_length=1)
    status_file: str | None = Field(default=None, pattern=r"^job-\d+\.status$")
    status_contents: str | None = None

    @model_validator(mode="after")
    def validate_status_file(self):
        if (self.status_file is None) != (self.status_contents is None):
            raise ValueError("Incomplete ephemeral status fixture")
        return self


def revision(path: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()


def bind(path: Path, target: str, *, writable: bool = False) -> str:
    suffix = "" if writable else ",readonly"
    return f"type=bind,source={path},target={target}{suffix}"


def official(image: str, upstream: Path, *args: str, action: str, timeout: int) -> str:
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "65534:65534",
        "--workdir",
        "/upstream",
        "--tmpfs",
        "/tmp:mode=1777",
        "--tmpfs",
        f"{WORK_VOLUME}:rw,exec,nosuid,nodev,mode=1777,size=1g",
        "--mount",
        bind(upstream, "/upstream"),
        "--mount",
        bind(HERE, "/adapter"),
        "-e",
        "PYTHONPATH=/upstream",
        "-e",
        "HOME=/tmp",
        "-e",
        "OPENBLAS_NUM_THREADS=1",
        *args,
        image,
        "python",
        "/adapter/upstream.py",
        action,
    ]
    return subprocess.check_output(
        command, text=True, encoding="utf-8", timeout=timeout
    )


def source_identity(upstream: Path) -> dict[str, object]:
    external = upstream / "bench/external"
    identities = {
        "ctxagent": revision(upstream),
        "polyglot": revision(external / "polyglot-benchmark"),
        "scicode": revision(external / "SciCode"),
        "letta": revision(external / "letta-evals"),
    }
    if tuple(identities.values()) != (
        UPSTREAM_REVISION,
        POLYGLOT_REVISION,
        SCICODE_REVISION,
        LETTA_REVISION,
    ):
        raise ValueError(f"Unexpected official source revisions: {identities}")
    targets = external / "SciCode/eval/data/test_data.h5"
    if sha256(targets) != H5_SHA256:
        raise ValueError("SciCode reference data checksum mismatch")
    for checkout in (
        upstream,
        *(external / name for name in ("polyglot-benchmark", "SciCode", "letta-evals")),
    ):
        subprocess.run(
            ["git", "-C", str(checkout), "diff", "--quiet", "HEAD", "--"], check=True
        )
    return {
        "source": identities,
        "scicode_targets": H5_SHA256,
        "scicode_dev": sha256(targets.with_name("problems_dev.jsonl")),
    }


def prepare(args) -> int:
    upstream, output = args.upstream, args.output
    identity = source_identity(upstream)
    output.mkdir(parents=True, exist_ok=False)
    image = docker("image", "inspect", args.image, "--format", "{{.Id}}")
    official(
        image,
        upstream,
        "--mount",
        bind(output, "/export", writable=True),
        action="prepare",
        timeout=180,
    )
    case = json.loads((output / "case.json").read_bytes())
    write_record(
        output / "source.json",
        {
            **identity,
            "task": "marathon:0",
            "image": image,
            "case": case,
        },
    )
    seal(output)
    print(json.dumps(case))
    return 0


@contextmanager
def workspace(image: str, prepared: Path, output: Path, *, personal_side: bool):
    if personal_side:
        work = extract_host_workspace(prepared / "workspace.tar", output / "native-workspace")
        yield work.parent, None
        return
    volume = docker("volume", "create", "marathon-" + uuid4().hex)
    try:
        with container(
            image,
            "--user",
            "0:0",
            "--network",
            "none",
            "--read-only",
            "--workdir",
            "/volume",
            "--mount",
            f"type=volume,source={volume},target=/volume,volume-nocopy",
            "--mount",
            bind(prepared / "workspace.tar", "/seed.tar"),
            command=("tar", "-xf", "/seed.tar", "--no-same-owner"),
        ) as initializer:
            docker("start", "-a", initializer)
        # Set ownership from the pinned archive before either agent can run.
        with container(
            image,
            "--user",
            "0:0",
            "--network",
            "none",
            "--read-only",
            "--workdir",
            "/volume",
            "--mount",
            f"type=volume,source={volume},target=/volume,volume-nocopy",
            command=("chown", "-hR", "65534:65534", "work"),
        ) as owner:
            docker("start", "-a", owner)
        yield volume, None
    finally:
        docker("volume", "rm", volume)


def probe_workspace(sandbox: str) -> str:
    return docker(
        "exec", sandbox, "sh", "-ec",
        "test -w .; test -d python; test -d javascript; test -d go; test -w .scratch; "
        "test ! -e /upstream; test ! -e /adapter; test ! -e /seed.tar; test ! -e /answers.json; "
        'test -z "$(find . -name .meta -print -quit)"; '
        "python --version; go version; node --version; /opt/marathon/node_modules/.bin/jest --version",
    )


def stage_status(sandbox: str, previous: list[str], turn: Turn) -> None:
    if previous:
        docker(
            "exec",
            sandbox,
            "sh",
            "-ec",
            'test ! -L jobs; rm -f -- "$@"',
            "stage",
            *(f"jobs/{name}" for name in previous),
        )
    if turn.status_file is not None:
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                sandbox,
                "sh",
                "-ec",
                'test ! -L jobs; mkdir -p jobs; set -C; cat > "jobs/$1"',
                "stage",
                turn.status_file,
            ],
            input=turn.status_contents.encode("utf-8"),
            check=True,
            timeout=20,
        )
        previous.append(turn.status_file)


def stage_host_status(work: Path, previous: list[str], turn: Turn) -> None:
    jobs = work / "jobs"
    if jobs.is_symlink():
        raise ValueError("The Marathon status directory cannot be a symlink")
    for name in previous:
        (jobs / name).unlink(missing_ok=True)
    if turn.status_file is not None:
        jobs.mkdir(exist_ok=True)
        with (jobs / turn.status_file).open("x", encoding="utf-8") as stream:
            stream.write(turn.status_contents)
        previous.append(turn.status_file)



def run_side(side: str, args, turns: tuple[Turn, ...], image: str) -> dict:
    output = args.output / side
    output.mkdir()
    answers = []
    requested = 0
    tokens = 0
    stop = "completed"
    error = None
    started = monotonic()
    with workspace(image, args.prepared, output, personal_side=side == "personal") as (volume, sandbox):
        try:
            driver = (
                personal(
                    output,
                    volume / "work",
                    args.model_env,
                    args.postgres_image,
                )
                if side == "personal"
                else harness(
                    output,
                    args.harness_image,
                    args.harness_source,
                    args.model_env,
                    volume,
                )
            )
            with driver as active:
                submit, active_sandbox = (active, sandbox) if side == "personal" else active
                if side == "deepseek":
                    write_record(output / "sandbox.json", {"tools": probe_workspace(active_sandbox)})
                staged: list[str] = []
                for turn in turns:
                    if tokens >= TASK_TOKENS or (output / "stop-after-turn").exists():
                        stop = (
                            "case_token_limit"
                            if tokens >= TASK_TOKENS
                            else "operator_stop_after_turn"
                        )
                        break
                    if side == "personal":
                        stage_host_status(volume / "work", staged, turn)
                    else:
                        stage_status(active_sandbox, staged, turn)
                    requested += 1
                    write_record(
                        output / "progress.json",
                        {
                            "requested": requested,
                            "delivered": sum(a.completed for a in answers),
                            "known_tokens": tokens,
                        },
                    )
                    delivery = submit(turn.number, turn.prompt)
                    answers.append(delivery)
                    tokens += delivery.tokens
                    write_record(
                        output / "answers.json",
                        [item.model_dump(mode="json") for item in answers],
                    )
                    write_record(
                        output / "progress.json",
                        {
                            "requested": requested,
                            "delivered": sum(a.completed for a in answers),
                            "known_tokens": tokens,
                        },
                    )
                    if not delivery.terminal:
                        stop = delivery.reason
                        break
        except Exception as exc:
            stop = "adapter_failure"
            error = f"{type(exc).__name__}: {exc}"
            for key, value in dotenv_values(args.model_env).items():
                if value and (key.endswith("_KEY") or "SECRET" in key):
                    error = error.replace(value, "[redacted]")
        generation_seconds = round(monotonic() - started, 3)
        if answers:
            try:
                shutil.copyfile(HERE / "upstream.py", output / "grader-adapter.py")
                result = official(
                    image,
                    args.upstream,
                    "--mount",
                    f"type={'bind' if side == 'personal' else 'volume'},source={volume},target=/submission,readonly",
                    "--mount",
                    bind(output / "answers.json", "/answers.json"),
                    action="grade",
                    timeout=14400,
                )
                write_record(output / "scores.json", json.loads(result))
            except (subprocess.SubprocessError, ValueError) as exc:
                error = f"{error or ''}\nOfficial grading: {exc}"
        if side == "personal":
            def keep(entry: tarfile.TarInfo) -> tarfile.TarInfo | None:
                return None if entry.name == "./.scratch" else entry

            with tarfile.open(output / "workspace.tar", "w") as archive:
                archive.add(volume / "work", arcname=".", filter=keep)
        else:
            with (output / "workspace.tar").open("wb") as archive:
                subprocess.run(
                    [
                        "docker",
                        "run", "--rm", "--network", "none", "--read-only", "--user", "65534:65534",
                        "--mount", f"type=volume,source={volume},target={WORK_VOLUME},readonly",
                        "--workdir", f"{WORK_VOLUME}/work", image, "tar", "--exclude=./.scratch",
                        "-cf",
                        "-",
                        ".",
                    ],
                    stdout=archive,
                    check=True,
                    timeout=120,
                )
    result = summarize(answers, output, requested, stop, error, generation_seconds)
    write_record(output / "report.json", result)
    seal(output)
    return result


def summarize(
    answers: list[Delivery],
    output: Path,
    requested: int,
    stop: str,
    error: str | None,
    generation_seconds: float | None,
) -> dict:
    scores = output / "scores.json"
    rows = json.loads(scores.read_bytes()) if scores.exists() else []
    compactions: Counter[str] = Counter()
    for item in answers:
        compactions.update(item.compaction_events)
    summary_turns = [
        item.number
        for item in answers
        if any(
            item.compaction_events.get(kind)
            for kind in ("history_compaction", "compaction/summary")
        )
    ]
    probes_after_summary = [
        row
        for row in rows
        if row["kind"] in {"probe_fact", "probe_ephemeral"}
        and any(
            row["meta"]["establish_turn"] < turn <= row["number"]
            for turn in summary_turns
        )
    ]
    return {
        "requested": requested,
        "delivered": sum(a.completed for a in answers),
        "unrequested": 212 - requested,
        "scored": sum(row["scored"] for row in rows),
        "passed": sum(row["scored"] and row["score"] == 1 for row in rows),
        "grader_errors": sum("check_error" in row["details"] for row in rows),
        "probes": {
            kind: {
                "scored": sum(row["kind"] == kind for row in rows),
                "passed": sum(
                    row["kind"] == kind and row["score"] == 1 for row in rows
                ),
            }
            for kind in ("probe_fact", "probe_ephemeral")
        },
        "rule_checks": sum(len(row["rules"]) for row in rows),
        "rules_followed": sum(
            rule["ok"] for row in rows for rule in row["rules"].values()
        ),
        "summary_turns": summary_turns,
        "probes_after_summary": {
            "scored": len(probes_after_summary),
            "passed": sum(row["score"] == 1 for row in probes_after_summary),
        },
        "known_tokens": sum(item.tokens for item in answers),
        "model_requests": sum(item.model_requests for item in answers),
        "peak_input": max(
            (item.peak_input for item in answers if item.peak_input is not None),
            default=None,
        ),
        "compaction_events": compactions,
        "generation_seconds": generation_seconds,
        "stop": stop,
        "error": error,
    }


def run(args) -> int:
    verify_seal(args.prepared)
    case = json.loads((args.prepared / "source.json").read_bytes())
    if (
        any(
            case.get(name) != value
            for name, value in source_identity(args.upstream).items()
        )
    ):
        raise ValueError("The execution source revisions do not match the frozen plan")
    harness_image = docker("image", "inspect", args.harness_image, "--format", "{{.Id}}")
    args.output.mkdir(parents=True, exist_ok=False)
    model_env = dotenv_values(args.model_env)
    capacity = json.loads(model_env["STRUCTURED_MODEL_CAPACITY"])
    if (
        capacity["model"] != model_env["STRUCTURED_MODEL"]
        or capacity["context_window_tokens"] != WINDOW
    ):
        raise ValueError("Both agents require the declared model and 1M context window")
    turns = tuple(
        Turn.model_validate(row)
        for row in json.loads((args.prepared / "turns.json").read_bytes())
    )
    if tuple(turn.number for turn in turns) != tuple(range(1, 213)):
        raise ValueError("Expected the complete official Marathon session")
    _source_identity(args.output)
    shutil.copytree(
        HERE,
        args.output / "source-snapshot/evals/marathon",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    write_record(
        args.output / "plan.json",
        {
            "case": case,
            "model": model_env["STRUCTURED_MODEL"],
            "model_window": WINDOW,
            "task_token_limit": TASK_TOKENS,
            "turn_timeout": TURN_TIMEOUT,
            "turns": len(turns),
            "harness_version": DSH_VERSION,
            "harness_image": harness_image,
            "prepared_checksums": sha256(args.prepared / "checksums.json"),
            "adapter_source": {
                path.name: sha256(path)
                for path in sorted(HERE.iterdir())
                if path.is_file()
            },
        },
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {
            side: pool.submit(run_side, side, args, turns, case["image"])
            for side in ("personal", "deepseek")
        }
        results = {}
        for side, job in jobs.items():
            try:
                results[side] = job.result()
            except Exception as exc:
                directory = args.output / side
                answers_file = directory / "answers.json"
                answers = (
                    [
                        Delivery.model_validate(row)
                        for row in json.loads(answers_file.read_bytes())
                    ]
                    if answers_file.exists()
                    else []
                )
                progress = directory / "progress.json"
                requested = (
                    json.loads(progress.read_bytes())["requested"]
                    if progress.exists()
                    else 0
                )
                results[side] = summarize(
                    answers,
                    directory,
                    requested,
                    "sandbox_or_archive_failure",
                    f"{type(exc).__name__}: {exc}",
                    None,
                )
                write_record(directory / "report.json", results[side])
    write_record(args.output / "comparison.json", results)
    seal(args.output)
    print(json.dumps(results, ensure_ascii=False))
    return int(
        any(
            side["delivered"] != len(turns) or side["error"] or side["grader_errors"]
            for side in results.values()
        )
    )


def regrade(args) -> int:
    verify_seal(args.capture)
    plan = json.loads((args.capture / "plan.json").read_bytes())
    case = plan["case"]
    if any(
        case.get(name) != value
        for name, value in source_identity(args.upstream).items()
    ):
        raise ValueError("Official source differs from the captured trial")
    args.output.mkdir(parents=True, exist_ok=False)
    image = case["image"]
    reports = {}
    for side in ("personal", "deepseek"):
        capture = args.capture / side
        answers = capture / "answers.json"
        if not answers.is_file():
            reports[side] = {"status": "no_deliveries"}
            continue
        volume = docker("volume", "create", "marathon-grade-" + uuid4().hex)
        try:
            with container(
                image,
                "--user",
                "0:0",
                "--network",
                "none",
                "--read-only",
                "--workdir",
                "/volume",
                "--mount",
                f"type=volume,source={volume},target=/volume,volume-nocopy",
                "--mount",
                bind(capture / "workspace.tar", "/submission.tar"),
                command=(
                    "sh",
                    "-ec",
                    "mkdir work; tar -C work -xf /submission.tar --no-same-owner",
                ),
            ) as initializer:
                docker("start", "-a", initializer)
            output = args.output / side
            output.mkdir()
            source_report = json.loads((capture / "report.json").read_bytes())
            result = official(
                image,
                args.upstream,
                "--mount",
                f"type=volume,source={volume},target=/submission,readonly",
                "--mount",
                bind(answers, "/answers.json"),
                action="grade",
                timeout=14400,
            )
            write_record(output / "scores.json", json.loads(result))
            deliveries = [
                Delivery.model_validate(row) for row in json.loads(answers.read_bytes())
            ]
            if side == "deepseek":
                for delivery in deliveries:
                    event_file = capture / f"turn-{delivery.number:03}.json"
                    delivery.tokens, delivery.peak_input = harness_usage(
                        json.loads(event_file.read_bytes())["events"]
                    )
            reports[side] = summarize(
                deliveries,
                output,
                source_report["requested"],
                source_report["stop"],
                None,
                source_report["generation_seconds"],
            )
            write_record(output / "report.json", reports[side])
        finally:
            docker("volume", "rm", volume)
    write_record(args.output / "comparison.json", reports)
    write_record(
        args.output / "source.json",
        {
            "capture": str(args.capture),
            "capture_checksums": sha256(args.capture / "checksums.json"),
            "adapter_sha256": sha256(HERE / "upstream.py"),
            "grading_image": image,
        },
    )
    shutil.copyfile(HERE / "upstream.py", args.output / "grader-adapter.py")
    seal(args.output)
    print(json.dumps(reports, ensure_ascii=False))
    return int(any(report.get("grader_errors") for report in reports.values()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    launch = commands.add_parser("run")
    grading = commands.add_parser("grade")
    for command in (prep, launch, grading):
        command.add_argument(
            "--upstream", type=lambda x: Path(x).resolve(), required=True
        )
        command.add_argument(
            "--output", type=lambda x: Path(x).resolve(), required=True
        )
    prep.add_argument("--image", default=DEFAULT_IMAGE)
    for name in ("prepared", "model-env"):
        launch.add_argument(
            f"--{name}", type=lambda x: Path(x).resolve(), required=True
        )
    launch.add_argument("--harness-source", type=lambda x: Path(x).resolve(), default=CHECKOUT)
    launch.add_argument("--harness-image", default="personal-agent-dsh-marathon:local")
    launch.add_argument("--postgres-image", default="postgres:16-alpine")
    grading.add_argument("--capture", type=lambda x: Path(x).resolve(), required=True)
    args = parser.parse_args()
    return {"prepare": prepare, "run": run, "grade": regrade}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
