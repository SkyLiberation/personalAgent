"""Collect, capture and grade the fixed five-question BrowseComp-Plus comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

from dotenv import dotenv_values

from evals.longDS.run_longds_harness import write_record
from evals.run_deepseek_harness import sha256

from .agents import Delivery, ModelSettings, harness, personal
from .data import CORPUS_REV, IDS, INDEX_REV, QUESTION_REV, UPSTREAM, Question, artifacts, select
from .grade import score
from .retrieval import MODEL, serve, siliconflow

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
IMAGE = "personal-agent-dsh-runtime:0.2.2-rc.5"
SIDES = ("personal", "deepseek")
PROBE = Question(
    query_id="environment-probe",
    query="Use the search tool to find a document about the Apollo 11 moon landing. "
    "Then call get_document on the first search result. Return its document ID only.",
)


def code_identity() -> dict:
    def git(*args: str) -> bytes:
        return subprocess.check_output(("git", "-C", str(ROOT), *args))

    patch_digest = hashlib.sha256(git("diff", "HEAD", "--binary")).hexdigest()
    paths = git("ls-files", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0")
    return {
        "commit": git("rev-parse", "HEAD").decode().strip(),
        "dirty_patch_sha256": patch_digest,
        "untracked_files": {path: sha256(ROOT / path) for path in paths if path and (ROOT / path).is_file()},
    }


def seal(output: Path) -> None:
    manifest = output / "checksums.sha256"
    paths = sorted(path for path in output.rglob("*") if path.is_file() and path != manifest)
    manifest.write_text("".join(f"{sha256(path)}  {path.relative_to(output).as_posix()}\n" for path in paths),
                        encoding="utf-8")


def require_seal(capture: Path) -> None:
    manifest = capture / "checksums.sha256"
    for row in manifest.read_text(encoding="utf-8").splitlines():
        expected, relative = row.split("  ", 1)
        if sha256(capture / relative) != expected:
            raise ValueError(f"Capture checksum mismatch for {relative}")


def run_side(action: Callable[[Path], Delivery], output: Path, log: Path) -> Delivery:
    output.mkdir(parents=True)
    start = log.stat().st_size if log.exists() else 0
    began = monotonic()
    try:
        result = action(output)
    except Exception as error:
        result = Delivery(reason=type(error).__name__, error=str(error))
    if log.exists():
        with log.open("rb") as source:
            source.seek(start)
            requests = source.read()
    else:
        requests = b""
    (output / "search-requests.jsonl").write_bytes(requests)
    calls = tuple(json.loads(line)["tool"] for line in requests.splitlines())
    result = result.model_copy(update={"tools_used": calls})
    write_record(output / "delivery.json", result.model_dump(mode="json"))
    print(f"{output.parent.name} {output.name}: {result.reason}, "
          f"{result.model_steps} model steps, {len(calls)} retrieval calls, {monotonic() - began:.1f}s",
          flush=True)
    return result


def probe_succeeded(result: Delivery, side: Path) -> bool:
    calls = [json.loads(line) for line in (side / "search-requests.jsonl").read_bytes().splitlines()]
    hits = {docid for call in calls if call["tool"] == "search" for docid in call["docids"]}
    return result.completed and any(
        call["tool"] == "get_document" and call["found"] and call["docid"] in hits for call in calls
    )


def capture(args: argparse.Namespace) -> None:
    questions = tuple(
        question for question in select(args.upstream) if args.query_id is None or question.query_id == args.query_id
    )
    values = dotenv_values(args.model_env)
    model = ModelSettings.from_env(values)
    embedding_url, _ = siliconflow(values)
    material = artifacts(args.cache, "verify")
    output = args.output
    output.mkdir(parents=True)
    log = output / "mcp-requests.jsonl"
    write_record(output / "plan.json", {
        "code": code_identity(),
        "dataset": {"upstream": UPSTREAM, "questions": QUESTION_REV, "index": INDEX_REV, "corpus": CORPUS_REV},
        "query_ids": [question.query_id for question in questions], "trials_per_side": 1, "materials_sha256": material,
        "chat_model": model.model, "chat_host": urlsplit(model.base_url).hostname,
        "embedding_model": MODEL, "embedding_host": urlsplit(embedding_url).hostname,
        "personal_goal_mode": "disabled", "personal_tool_call_limit": None, "harness_image": args.harness_image,
        "preflight_only": args.preflight_only,
    })
    try:
        with serve(args.cache, values, log) as port:
            def pair(question: Question) -> dict[str, Delivery]:
                result = {
                    "personal": run_side(
                        lambda directory: personal(question, directory, port, args.model_env, model),
                        output / question.query_id / "personal", log,
                    ),
                    "deepseek": run_side(
                        lambda directory: harness(question, directory, port, values, model, args.harness_image),
                        output / question.query_id / "deepseek", log,
                    ),
                }
                return result

            probe = pair(PROBE)
            if not all(probe_succeeded(item, output / PROBE.query_id / side) for side, item in probe.items()):
                raise RuntimeError("Both solvers must reach the same two tools before real questions run")
            if not args.preflight_only:
                for question in questions:
                    pair(question)
    finally:
        seal(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    for mode in ("collect", "download", "run", "grade"):
        command = modes.add_parser(mode)
        if mode != "download":
            command.add_argument("--upstream", type=Path, required=True)
        if mode in {"download", "run"}:
            command.add_argument("--cache", type=Path, required=True)
        if mode in {"run", "grade"}:
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--model-env", type=Path, default=Path(".env"))
        if mode == "run":
            command.add_argument("--harness-image", default=IMAGE)
            command.add_argument("--query-id", choices=IDS)
            command.add_argument("--preflight-only", action="store_true")
        if mode == "grade":
            command.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    match args.mode:
        case "collect":
            print(json.dumps({"ids": [item.query_id for item in select(args.upstream)], "sides": SIDES}))
        case "download":
            print(json.dumps(artifacts(args.cache, "download"), indent=2))
        case "run":
            capture(args)
        case "grade":
            require_seal(args.capture)
            args.output.mkdir(parents=True)
            try:
                write_record(args.output / "identity.json", {
                    "capture_seal_sha256": sha256(args.capture / "checksums.sha256"),
                    "scoring_source_sha256": {
                        name: sha256(HERE / name) for name in ("agents.py", "data.py", "grade.py")
                    },
                    "upstream_scoring_sha256": sha256(args.upstream / "scripts_evaluation/evaluate_run.py"),
                })
                query_ids = tuple(json.loads((args.capture / "plan.json").read_bytes())["query_ids"])
                if not query_ids or len(set(query_ids)) != len(query_ids) or any(query not in IDS for query in query_ids):
                    raise ValueError("Capture plan contains invalid BrowseComp-Plus question IDs")
                summary = score(args.upstream, dotenv_values(args.model_env), args.capture, args.output, query_ids)
            finally:
                seal(args.output)
            print(json.dumps({key: summary[key] for key in ("scored", "scored_pairs", "pass")}))


if __name__ == "__main__":
    main()
