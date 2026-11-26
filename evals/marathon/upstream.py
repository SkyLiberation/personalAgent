"""Prepare and grade the published session inside the isolated Linux tool image."""

from collections import Counter
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile

from bench.run import PREAMBLE, SCORED_KINDS
from bench.tasks_mix import build_marathon
from bench import tasks_polyglot


TRIAL = Path("/workspace/marathon")
SUBMISSION = Path("/submission/work")
EXPORT = Path("/export")
JS_MODULES = Path("/opt/marathon/node_modules")


def prepare(work: Path, specs: list[dict]) -> None:
    for link in work.glob("javascript/*/node_modules"):
        link.unlink()
        link.symlink_to(JS_MODULES, target_is_directory=True)
    (work / ".scratch").mkdir()
    with tarfile.open(EXPORT / "workspace.tar", "w") as archive:
        archive.add(work, arcname="work")

    planned = []
    for i, spec in enumerate(specs, 1):
        spec["pre"]()
        path = Path(spec["meta"]["path"]) if spec["kind"] == "ephemeral" else None
        prompt = spec["prompt"].replace(
            r"node_modules\.bin\jest", "node_modules/.bin/jest"
        )
        planned.append(
            {
                "number": i,
                "kind": spec["kind"],
                "prompt": f"{PREAMBLE}\n\n{prompt}" if i == 1 else prompt,
                "status_file": path.name if path else None,
                "status_contents": path.read_text(encoding="utf-8") if path else None,
            }
        )
    (EXPORT / "turns.json").write_text(
        json.dumps(planned, ensure_ascii=False), encoding="utf-8"
    )
    (EXPORT / "case.json").write_text(
        json.dumps(
            {
                "turns": len(planned),
                "kinds": Counter(item["kind"] for item in planned),
                "tracks": Counter(
                    spec["meta"]["lang"] for spec in specs if "lang" in spec["meta"]
                ),
                "scicode_steps": sum("step" in spec["meta"] for spec in specs),
            }
        ),
        encoding="utf-8",
    )


def grade(work: Path, specs: list[dict], answers_file: Path) -> None:
    if os.statvfs(work).f_flag & os.ST_NOEXEC:
        raise RuntimeError("Official Go grading needs an executable scratch mount")
    # Build closures against the official files before overlaying submitted files.
    # In particular, the exercise grader keeps the original test-file hashes.
    shutil.rmtree(work)
    shutil.copytree(
        SUBMISSION, work, symlinks=True, ignore=shutil.ignore_patterns(".scratch")
    )
    (work / ".scratch").mkdir()
    rows = []
    history = []
    for spec, delivery in zip(
        specs, json.loads(answers_file.read_text(encoding="utf-8"))
    ):
        number = len(rows) + 1
        if delivery["number"] != number:
            raise ValueError("Submission turns must be consecutive from turn 1")
        final = delivery["answer"]
        if delivery["completed"]:
            try:
                score, details = spec["check"](final, history)
                rules = spec["rules"](final)
            except Exception as exc:
                score, details, rules = (
                    0.0,
                    {"check_error": f"{type(exc).__name__}: {exc}"},
                    {},
                )
        else:
            score, details, rules = 0.0, {"harness_error": delivery["reason"]}, {}
        rows.append(
            {
                "number": number,
                "kind": spec["kind"],
                "score": score,
                "details": details,
                "rules": rules,
                "meta": spec["meta"],
                "scored": spec["kind"] in SCORED_KINDS,
            }
        )
        history.append(
            {
                "turn": number,
                "kind": spec["kind"],
                "prompt": spec["prompt"],
                "final": final,
                "meta": spec["meta"],
            }
        )
    print(json.dumps(rows, ensure_ascii=False))


def main() -> None:
    tasks_polyglot.GO_BIN = Path("/opt/go/bin")
    tasks_polyglot.JS_NODE_MODULES = JS_MODULES
    work, specs = build_marathon("marathon:0", TRIAL)
    if len(specs) != 212 or sum("lang" in s["meta"] for s in specs) != 118:
        raise ValueError("Incomplete marathon:0 toolchains or incompatible dataset")
    if sys.argv[1] == "prepare":
        prepare(work, specs)
    else:
        grade(work, specs, Path("/answers.json"))


if __name__ == "__main__":
    main()
