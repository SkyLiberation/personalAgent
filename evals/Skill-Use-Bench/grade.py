"""Adapt native tool records to the upstream rubric and verify the delivered PDF."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys

from dotenv import dotenv_values
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from evals.longDS.longds_materials import seal, verify_seal
from evals.longDS.run_longds_harness import write_record
from personal_agent.application.bash_execution.models import BashToolResult


SKILL = "pdftk-server"


def read(path: Path):
    return json.loads(path.read_bytes())


def skill_catalogs(request: dict) -> list[list[str]]:
    catalogs = []
    for message in request["messages"]:
        content = message.get("content")
        if message["role"] != "user" or not isinstance(content, str):
            continue
        _, marker, body = content.partition("<available_skills>\n")
        if marker:
            catalogs.append([
                json.loads(line[2:])["name"] for line in body.split("\n</available_skills>", 1)[0].splitlines()
                if line.startswith("- ")
            ])
    return catalogs


def skill_requests(side: Path):
    for path in (side / "sdk").glob("*.http.request.json"):
        request = read(path)
        for item in request.get("tools", []):
            if item.get("function", {}).get("name") == "tool_load_skill":
                yield request, item["function"]["description"]


def scope_grade(side: Path, expected_source: str, instructions: str) -> dict:
    requests = list(skill_requests(side))
    trace = read(side / "turn-001.trace.json")
    loaded = {
        item["action_id"]: item["payload"]["data"]
        for item in trace["inputs"]
        if item["kind"] == "tool_result" and item["capability_id"] == "load_skill" and item["payload"]["ok"]
    }
    visible_once = bool(requests) and all(skill_catalogs(request) == [[SKILL]] for request, _ in requests)
    matching_receipts = {
        call_id for call_id, data in loaded.items()
        if data["name"] == SKILL and data.get("source") == expected_source
        and data["instructions"].strip() == instructions
    }
    body_sent = any(
        message.get("tool_call_id") in matching_receipts
        and (message.get("content") or "").partition("<skill_instructions>\n")[2]
        .partition("\n</skill_instructions>")[0].strip() == instructions
        for request, _ in requests for message in request["messages"] if message["role"] == "tool"
    )
    return {
        "expected_source": expected_source, "sources": sorted({data.get("source") for data in loaded.values()}, key=str),
        "visible_once": visible_once, "body_sent": body_sent,
        "passed": visible_once and bool(loaded) and set(loaded) == matching_receipts and body_sent,
    }


def project_calls(side: Path, instructions: str) -> tuple[list[dict], str, bool]:
    if side.name == "deepseek-harness":
        trace = read(side / "turn-001.json")
        events = trace["events"]
        registered = any(
            event["type"] == "user/message"
            and (source := event["data"].get("source", {})).get("kind") == "skill-catalog"
            and any(entry["name"] == SKILL for entry in source["entries"])
            for event in events
        )
        results = {}
        for event in events:
            if event["type"] == "tool/result":
                message = event["data"]["message"]
                body = "\n".join(
                    part["text"] for part in message["content"] if part["type"] == "text"
                )
                returned = body.partition("<skill_instructions>\n")[2].partition("\n</skill_instructions>")[0]
                results[message["toolCallId"]] = body, not message.get("isError") and returned.strip() == instructions
        tools = [event["data"] for event in events if event["type"] == "tool/call"]
        calls = [(tool["callId"], tool["name"], tool["arguments"]) for tool in tools]
    else:
        trace = read(side / "turn-001.trace.json")
        registered = any(
            f'"name": "{SKILL}"' in description or any(SKILL in names for names in skill_catalogs(request))
            for request, description in skill_requests(side)
        )
        results = {}
        for result in trace["inputs"]:
            if result["kind"] != "tool_result":
                continue
            payload = result["payload"]
            result_data = payload["data"]
            if result["capability_id"] == "bash" and result_data:
                body = BashToolResult.model_validate(result_data).shell_output()
            else:
                body = json.dumps(result_data, ensure_ascii=False) if payload["ok"] else (payload["error"] or "Tool failed")
            loaded = result["capability_id"] == "load_skill" and payload["ok"] and result_data["instructions"].strip() == instructions
            results[result["action_id"]] = body, loaded
        calls = []
        for record in trace["model_decisions"]:
            payload = (record.get("assistant") or {}).get("payload") or {}
            for tool in payload.get("tool_calls") or []:
                function = tool["function"]
                calls.append((tool["id"], function["name"], function["arguments"]))
    steps = []
    for call_id, name, arguments in calls:
        if call_id not in results:
            continue
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
        result, loaded = results[call_id]
        tool = name
        if name in {"tool_bash", "bash"}:
            tool = "Bash"
        elif name in {"skill", "tool_load_skill"} and loaded:
            tool = "Skill"
            args = {"skill": args["name"]}
        steps.append({"id": call_id, "tool": tool, "native_name": name, "args": args, "result": result})
    return steps, read(side / "result.json")["delivery"]["answer"], registered


def normalize(side: Path, steps: list[dict], answer: str, registered: bool) -> Path:
    """Use the upstream stream schema without altering command text or tool output."""
    destination = side / "rubric-trace.jsonl"
    records = [{"type": "system", "subtype": "init",
                "skills": [SKILL] if registered else [],
                "adapter": side.name}]
    for idx, step in enumerate(steps):
        call_id = step["id"]
        for kind, data in (
            ("content_block_start", {"content_block": {"type": "tool_use", "id": call_id, "name": step["tool"]}}),
            ("content_block_delta", {"delta": {"type": "input_json_delta", "partial_json": json.dumps(step["args"], ensure_ascii=False)}}),
            ("content_block_stop", {}),
        ):
            records.append({"type": "stream_event", "event": {"type": kind, "index": idx, **data}})
        records.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": call_id, "content": step["result"]},
        ]}})
    records.append({"type": "result", "result": answer})
    destination.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
    write_record(side / "tool-projection.json", [{"id": s["id"], "native_name": s["native_name"], "rubric_name": s["tool"]} for s in steps])
    return destination


def page_signatures(pdf: Path, image: str) -> tuple[list[str], list[tuple]]:
    text = subprocess.check_output([
        "docker", "run", "--rm", "-i", "--network", "none", "--read-only", image,
        "pdftotext", "-layout", "-", "-",
    ], input=pdf.read_bytes(), timeout=60)
    pages = text.removesuffix(b"\f").split(b"\f")
    geometry = [
        (tuple(round(float(value), 4) for value in page.mediabox), page.rotation)
        for page in PdfReader(pdf).pages
    ]
    if len(pages) != len(geometry):
        raise ValueError("Page count differs from the layout-text extraction")
    return [sha256(page).hexdigest() for page in pages], geometry


def pdf_grade(side: Path, seed: dict[str, str], expected: list[str], geometry: list[tuple], image: str, verifier) -> dict:
    artifacts = side / "artifacts"
    official = verifier(artifacts)
    outputs = []
    for candidate in sorted(artifacts.glob("*.pdf")):
        try:
            pages, output_geometry = page_signatures(candidate, image)
        except (ValueError, OSError, KeyError, PyPdfError, subprocess.SubprocessError) as exc:
            outputs.append({"file": candidate.name, "error": type(exc).__name__})
            continue
        outputs.append({
            "file": candidate.name, "pages": len(pages),
            "all_source_page_text": Counter(pages) == Counter(expected),
            "alphabetical_page_order": pages == expected,
            "page_geometry_preserved": Counter(zip(pages, output_geometry, strict=True))
            == Counter(zip(expected, geometry, strict=True)),
        })
    sandbox = read(side / "sandbox.json")
    final = {str(Path(name).name): digest for digest, name in (line.split(maxsplit=1) for line in sandbox["final_input_hashes"])}
    return {"official": official, "outputs": outputs, "inputs_unchanged": final == seed}


def scorer_entry(scorer: Path, output: Path) -> Path:
    if hasattr(signal, "SIGALRM"):
        return scorer
    # The Windows subprocess timeout bounds the scorer where POSIX alarms are unavailable.
    original = scorer.read_text(encoding="utf-8")
    marker = "        old = _signal.signal(_signal.SIGALRM, _regex_alarm)"
    if original.count(marker) != 1:
        raise ValueError("The pinned scorer changed its regex timeout implementation")
    portable = output / "score_trace_windows.py"
    portable.write_text(original.replace(
        marker, '        if not hasattr(_signal, "SIGALRM"):\n            return pat.search(text)\n' + marker,
    ), encoding="utf-8")
    return portable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-env", default=Path(".env"), type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    if (run / "checksums.json").exists():
        verify_seal(run)
    output = args.output.resolve()
    if output.is_relative_to(run):
        raise ValueError("The score archive must be separate from the raw run")
    output.mkdir(parents=True)
    official = run / "official"
    config = dotenv_values(args.model_env)
    model = config.get("LONGDS_JUDGE_MODEL")
    base_url = config.get("LONGDS_JUDGE_BASE_URL")
    key = config.get("LONGDS_JUDGE_API_KEY")
    if not (model and base_url and key):
        raise ValueError("The model file must configure the LongDS compatible judge")
    env = {**os.environ, "OPENAI_BASE_URL": base_url, "OPENAI_API_KEY": key,
           "SF_JUDGE_CONCURRENCY": "3", "PYTHONIOENCODING": "utf-8"}
    verifier = runpy.run_path(str(official / "verify_task_success.py"))["verify_t1_merge_unordered"]
    seed = read(run / "inputs.json")["seed_sha256"]
    instructions = (run / "skills" / SKILL / "SKILL.md").read_text(encoding="utf-8").split("\n---\n", maxsplit=1)[1].strip()
    image = next(read(path)["image"] for path in run.glob("*/sandbox.json"))
    scorer = scorer_entry(official / "score_trace.py", output)
    expected, geometry = [], []
    for pdf in sorted((run / "seed/work/docs").glob("*.pdf")):
        pages, dimensions = page_signatures(pdf, image)
        expected.extend(pages)
        geometry.extend(dimensions)
    info = read(run / "run.json")
    sides = info.get("agents", ("personal-agent", "deepseek-harness"))
    graded = {}
    scope_report = None
    for name in sides:
        side = run / name
        if "error" in read(side / "result.json"):
            continue
        scored = output / name
        scored.mkdir()
        trace = normalize(scored, *project_calls(side, instructions))
        graded[name] = pdf_grade(side, seed, expected, geometry, image, verifier)
        write_record(scored / "pdf-verification.json", graded[name])
        if name == "personal-agent" and info.get("personal_skill_scope") in {"project", "user"}:
            scope_report = scope_grade(side, info["personal_skill_scope"], instructions)
            write_record(scored / "scope-verification.json", scope_report)
        subprocess.run([
            sys.executable, str(scorer), "--trace", str(trace),
            "--rubric", str(official / "rubric.yaml"), "--job-dir", str(side / "artifacts"),
            "--judge-model", model, "--target-skill", SKILL, "--out", str(scored / "rubric-score.json"),
        ], check=True, env=env, timeout=480)
    write_record(output / "grade.json", {
        "judge": model, "scorer": scorer.name, "raw_run": str(run), "pdf_verification": graded,
        "scope_verification": scope_report,
    })
    (output / "grade_source.py").write_bytes(Path(__file__).read_bytes())
    seal(output)
    verify_seal(output)
    return int(len(graded) != len(sides) or (scope_report is not None and not scope_report["passed"]))


if __name__ == "__main__":
    raise SystemExit(main())
