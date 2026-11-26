"""Apply the pinned upstream BrowseComp-Plus answer judge through its hosted model."""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import httpx
from pydantic import BaseModel

from evals.longDS.run_longds_harness import write_record

from .agents import Delivery, personal_delivery
from .data import Reference, select
from .retrieval import siliconflow

MODEL = "Qwen/Qwen3-32B"
SAMPLING = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "max_tokens": 4096}


class JudgeResult(BaseModel):
    extracted_final_answer: str | None
    correct: bool | None
    confidence: float | None
    parse_error: bool
    judge_response: str


def upstream_rules(upstream: Path) -> SimpleNamespace:
    path = upstream / "scripts_evaluation/evaluate_run.py"
    source = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    wanted = {"create_judge_prompt", "parse_judge_response"}
    definitions = [
        node for node in source.body
        if (isinstance(node, ast.FunctionDef) and node.name in wanted)
        or (isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "GRADER_TEMPLATE" for target in node.targets
        ))
    ]
    rules = {"re": re}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(path), "exec"), rules)
    return SimpleNamespace(**{name: rules[name] for name in wanted})


def grade(client: httpx.Client, rules: SimpleNamespace, question: Reference, answer: str) -> JudgeResult:
    prompt = rules.create_judge_prompt(question.query, answer, question.answer)
    response = client.post("/chat/completions", json={
        "model": MODEL, "messages": [{"role": "user", "content": prompt}], **SAMPLING,
    }).raise_for_status().json()
    text = response["choices"][0]["message"]["content"] or ""
    return JudgeResult.model_validate({**rules.parse_judge_response(text), "judge_response": text})


def score(upstream: Path, values: Mapping[str, str | None], capture: Path, output: Path,
          query_ids: tuple[str, ...]) -> dict:
    references = {item.query_id: item for item in select(upstream, include_answers=True)}
    rules = upstream_rules(upstream)
    endpoint, headers = siliconflow(values)
    rows = []
    with httpx.Client(base_url=endpoint, headers=headers, timeout=180) as client:
        controls = Reference(query_id="calibration", query="Which planet is called the Red Planet?", answer="Mars")
        positive = grade(client, rules, controls, "The Red Planet is Mars.")
        negative = grade(client, rules, controls, "Venus.")
        write_record(output / "calibration.json", {"positive": positive.model_dump(), "negative": negative.model_dump()})
        if positive.parse_error or positive.correct is not True or negative.parse_error or negative.correct is not False:
            raise RuntimeError("The hosted upstream judge failed its scoring controls")
        for query_id in query_ids:
            record = {"query_id": query_id}
            for side in ("personal", "deepseek"):
                path = capture / query_id / side / "delivery.json"
                if not path.is_file():
                    record[side] = {"status": "not_executed"}
                    continue
                answer = Delivery.model_validate_json(path.read_bytes())
                capture_metadata = {}
                if side == "personal" and (path.parent / "turn-trace.json").is_file():
                    try:
                        verified = personal_delivery(path.parent)
                    except (OSError, ValueError, KeyError) as error:
                        record[side] = {"status": "capture_validation_error", "error": str(error)}
                        continue
                    if answer.error:
                        capture_metadata = {"capture_adapter_error": answer.reason, "source": "turn-response.json"}
                    answer = verified
                if answer.error:
                    record[side] = {"status": "runtime_error", "reason": answer.reason, "error": answer.error}
                    continue
                if not answer.completed or not answer.answer.strip():
                    record[side] = {"status": "no_final_answer", "reason": answer.reason, **capture_metadata}
                    continue
                try:
                    verdict = grade(client, rules, references[query_id], answer.answer)
                except (httpx.HTTPError, ValueError, KeyError, IndexError) as error:
                    record[side] = {"status": "grading_error", "error": str(error)}
                    continue
                record[side] = {
                    "status": "grading_error" if verdict.parse_error or verdict.correct is None
                    else "pass" if verdict.correct else "fail",
                    **verdict.model_dump(),
                    **capture_metadata,
                }
            rows.append(record)
            write_record(output / f"{query_id}.json", record)
    summary = {
        "grader_model": MODEL, "sampling": SAMPLING, "questions": rows,
        "pass": {side: sum(row[side]["status"] == "pass" for row in rows) for side in ("personal", "deepseek")},
        "scored": {side: sum(row[side]["status"] in {"pass", "fail"} for row in rows) for side in ("personal", "deepseek")},
        "scored_pairs": sum(
            all(row[side]["status"] in {"pass", "fail"} for side in ("personal", "deepseek")) for row in rows
        ),
    }
    write_record(output / "summary.json", summary)
    return summary
