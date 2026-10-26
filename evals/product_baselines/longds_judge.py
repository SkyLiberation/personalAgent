"""只读封存结果，以固定 LongDS 官方协议独立评分。

评分解析参考 DataMind / LongDS-Bench，Apache-2.0，
a814927159470ad1624602d233f57b7c0be5882e/longds/runners/src/judge.py。
"""

from __future__ import annotations

import argparse
import ast
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
from time import monotonic
from typing import Literal
from uuid import uuid4

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from personal_agent.adapters.web.routes.conversation import ConversationTurnResponse
from personal_agent.application.conversation.journal_lock import exclusive_run_lock
from personal_agent.application.python_execution.models import Digest

from .longds_materials import json_bytes, seal, verify_preparation, verify_seal
from .retrieval_capture_audit import ObservedProviderCompletion


PROMPT_SHA256 = "07844fdda634dcbb492e2ad2a9a5969cb3707de8f8b8c00c22d9817b320d2816"
JUDGE_SOURCE_SHA256 = "80ea064624368ca74ef9a7f900e1ff2ef423fd8ff5ca401dcb349d97bda2c9c6"
MODEL = "deepseek-v4-pro"
TOKEN_LIMIT = 2_000_000
OUTPUT_LIMIT = 32_768


class LongDSJudgement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    turn_id: int = Field(ge=1, le=50)
    score: Literal[0, 1] | None
    reasoning: str = ""
    error_detail: str = ""
    failure: Literal["service_failure", "unknown_usage", "protocol_failure", "budget_exhausted"] | None = None
    attempts: int = Field(ge=0, le=3)
    call_ids: tuple[str, ...] = ()


class JudgeConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model: Literal["deepseek-v4-pro"] = MODEL
    provider_host: Literal["api.deepseek.com"] = "api.deepseek.com"
    prompt_sha256: Digest = PROMPT_SHA256
    source_sha256: Digest = JUDGE_SOURCE_SHA256
    temperature: Literal[0] = 0
    max_tokens: Literal[32768] = OUTPUT_LIMIT
    timeout_seconds: Literal[480] = 480
    sdk_max_retries: Literal[0] = 0
    protocol_attempts: Literal[3] = 3
    total_token_limit: Literal[2000000] = TOKEN_LIMIT


class JudgeCallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    completed: bool
    request_sha256: Digest
    response: ObservedProviderCompletion | None
    exception_type: str | None
    wall_seconds: float = Field(ge=0)


class JudgeQualification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    configuration_digest: Digest
    positive: LongDSJudgement
    negative: LongDSJudgement | None
    known_tokens: int = Field(ge=0)
    unknown_usage_attempts: int = Field(ge=0)
    negative_source_sha256: Digest

    @property
    def qualified(self) -> bool:
        return (self.positive.score == 1 and self.positive.failure is None
                and self.negative is not None and self.negative.score == 0
                and self.negative.failure is None)


class JudgeScoreReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    configuration_digest: Digest
    capture_checksums_sha256: Digest
    qualification_checksums_sha256: Digest | None = None
    task_turns: int = Field(default=36, ge=1, le=50)
    turns: tuple[LongDSJudgement, ...]
    known_judge_tokens: int = Field(ge=0)
    unknown_usage_attempts: int = Field(ge=0)

    @property
    def judged_turns(self) -> int:
        return sum(x.score is not None for x in self.turns)

    @property
    def correct_turns(self) -> int:
        return sum(x.score == 1 for x in self.turns)


def load_prompt(source_directory: Path) -> str:
    source = (source_directory / "judge-prompt.py").read_bytes()
    if sha256(source).hexdigest() != PROMPT_SHA256:
        raise ValueError("官方Judge Prompt身份不符")
    if sha256((source_directory / "judge.py").read_bytes()).hexdigest() != JUDGE_SOURCE_SHA256:
        raise ValueError("官方Judge源码身份不符")
    for node in ast.parse(source.decode("utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id == "JUDGE_PROMPT" for x in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise ValueError("官方来源没有文字JUDGE_PROMPT")


def _format(value: object) -> str:
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else "" if value is None else str(value)


def _parse(text: str) -> tuple[int, str, str] | None:
    # 与固定官方 parse_judge_response 相同；不把模型故障计作语义0分。
    score_match = re.search(r"<score>\s*(\d)\s*</score>", text)
    if not score_match or int(score_match.group(1)) not in (0, 1):
        return None
    reasoning = re.search(r"<reasoning>(.*?)</reasoning>", text, re.DOTALL)
    error = re.search(r"<error>(.*?)</error>", text, re.DOTALL)
    return int(score_match.group(1)), reasoning.group(1).strip() if reasoning else "", error.group(1).strip() if error else ""


class MeteredJudge:
    def __init__(self, root: Path, *, source_directory: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.prompt = load_prompt(source_directory)
        self.configuration = JudgeConfiguration()
        self.configuration_digest = sha256(self.configuration.model_dump_json().encode()).hexdigest()
        config = self.root / "configuration.json"
        with exclusive_run_lock("judge:" + str(self.root), self.root / "writer.lock"):
            if config.exists() and JudgeConfiguration.model_validate_json(config.read_bytes()) != self.configuration:
                raise ValueError("不可在同一评分组中更换模型或协议")
            config.write_text(self.configuration.model_dump_json(indent=2), encoding="utf-8")
        key = os.environ.get("DEEPSEEK_API") or os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise ValueError("缺少现有DeepSeek评分凭据")
        self.client = OpenAI(api_key=key, base_url="https://api.deepseek.com", max_retries=0, timeout=480)

    def usage(self) -> tuple[int, int]:
        known = unknown = 0
        for request in self.root.rglob("call-*.request.json"):
            response = request.with_name(request.name.replace(".request.json", ".response.json"))
            if not response.is_file():
                unknown += 1
                continue
            record = JudgeCallRecord.model_validate_json(response.read_bytes())
            if record.request_sha256 != sha256(request.read_bytes()).hexdigest():
                raise ValueError("评分调用与原始请求字节不一致")
            usage = record.response.usage if record.response is not None else None
            if not record.completed or usage is None or any(getattr(usage, k) is None for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
                unknown += 1
            else:
                known += usage.total_tokens
        return known, unknown

    def judge(self, directory: Path, *, turn_id: int, context: str, question: str,
              answer: object, solution: str) -> LongDSJudgement:
        payload = {"model": MODEL, "temperature": 0, "max_tokens": OUTPUT_LIMIT,
                   "messages": [{"role": "user", "content": self.prompt.format(
                       question=f"Context:\n{context.strip()}\n\nQuestion:\n{question.strip()}",
                       ground_truth=_format(answer), solution=solution)}]}
        call_ids: list[str] = []
        for _ in range(3):
            with exclusive_run_lock("judge:" + str(self.root), self.root / "writer.lock"):
                used, _ = self.usage()
                if used + len(json_bytes(payload)) + OUTPUT_LIMIT + 8192 > TOKEN_LIMIT:
                    return LongDSJudgement(turn_id=turn_id, score=None, attempts=len(call_ids), call_ids=tuple(call_ids),
                        failure="budget_exhausted")
                call_id = "call-" + uuid4().hex
                call_ids.append(call_id)
                request_bytes = json_bytes(payload)
                (directory / f"{call_id}.request.json").write_bytes(request_bytes)
                started = monotonic()
                response = None
                failure = None
                observed = None
                try:
                    response = self.client.chat.completions.create(**payload)
                except Exception as error:
                    failure = type(error).__name__
                finally:
                    if response is not None:
                        raw = response.model_dump(mode="json")
                        (directory / f"{call_id}.raw-response.json").write_bytes(json_bytes(raw))
                        try:
                            observed = ObservedProviderCompletion.model_validate(raw)
                        except ValueError as error:
                            failure = type(error).__name__
                    record = JudgeCallRecord(completed=observed is not None,
                        request_sha256=sha256(request_bytes).hexdigest(),
                        response=observed,
                        exception_type=failure, wall_seconds=monotonic() - started)
                    (directory / f"{call_id}.response.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
                if not record.completed:
                    return LongDSJudgement(turn_id=turn_id, score=None, attempts=len(call_ids),
                                            call_ids=tuple(call_ids), failure="service_failure" if response is None else "protocol_failure")
                parsed = _parse(response.choices[0].message.content or "")
                if parsed is not None:
                    return LongDSJudgement(turn_id=turn_id, score=parsed[0], reasoning=parsed[1], error_detail=parsed[2],
                                            attempts=len(call_ids), call_ids=tuple(call_ids))
        return LongDSJudgement(turn_id=turn_id, score=None, attempts=len(call_ids),
                                call_ids=tuple(call_ids), failure="protocol_failure")


def qualify(judge: MeteredJudge, *, materials: Path, negative_capture: Path) -> None:
    verify_preparation(materials)
    verify_seal(negative_capture)
    reference = json.loads((materials / "evaluator-private/task.json").read_bytes())[0]
    actual = ConversationTurnResponse.model_validate_json((negative_capture / "turn-01.response.json").read_bytes())
    output = judge.root / "qualification"
    output.mkdir(exist_ok=False)
    source = Path(__file__).read_bytes()
    (output / "judge-source.py").write_bytes(source)
    (output / "identity.json").write_bytes(json_bytes({
        "judge_source_sha256": sha256(source).hexdigest(), "openai_version": version("openai"),
        "pydantic_version": version("pydantic"), "prompt_sha256": PROMPT_SHA256,
        "preparation_sha256": sha256((materials / "preparation.json").read_bytes()).hexdigest(),
        "source_language": "official English protocol with Chinese candidate answer",
    }))
    positive = judge.judge(output, turn_id=1, context=reference["context"], question=reference["question"],
                           answer=reference["answer"], solution=_format(reference["answer"]))
    negative = (judge.judge(output, turn_id=1, context=reference["context"], question=reference["question"],
                             answer=reference["answer"], solution=actual.message.content)
                if positive.failure is None else None)
    result = JudgeQualification(configuration_digest=judge.configuration_digest, positive=positive,
        negative=negative, known_tokens=judge.usage()[0], unknown_usage_attempts=judge.usage()[1],
        negative_source_sha256=sha256((negative_capture / "checksums.json").read_bytes()).hexdigest())
    (output / "report.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    seal(output)
    print(json.dumps({"qualified": result.qualified, "known_tokens": result.known_tokens,
                      "unknown_usage_attempts": result.unknown_usage_attempts}))


def score(judge: MeteredJudge, *, materials: Path, capture: Path, name: str,
          turn_ids: list[int] | None = None, qualification_directory: Path | None = None) -> None:
    from .run_longds import LongDSCapture

    prepared = verify_preparation(materials)
    verify_seal(capture)
    if not LongDSCapture.model_validate_json((capture / "report.json").read_bytes()).actual_process_stopped:
        raise ValueError("实际生成进程尚未停止，不得评分")
    qualification_directory = qualification_directory or judge.root / "qualification"
    verify_seal(qualification_directory)
    qualification = JudgeQualification.model_validate_json((qualification_directory / "report.json").read_bytes())
    if not qualification.qualified or qualification.configuration_digest != judge.configuration_digest:
        raise ValueError("本模型与协议的评分资格未通过")
    identity = json.loads((capture / "input-identity.json").read_bytes())
    if identity["preparation_sha256"] != sha256((materials / "preparation.json").read_bytes()).hexdigest():
        raise ValueError("评分输入与正式采集的准备身份不同")
    output = judge.root / name
    if output.parent != judge.root or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("评分输出名称不合法")
    output.mkdir(exist_ok=False)
    (output / "judge-source.py").write_bytes(Path(__file__).read_bytes())
    (output / "materials-source.py").write_bytes(Path(__file__).with_name("longds_materials.py").read_bytes())
    references = json.loads((materials / "evaluator-private/task.json").read_bytes())
    results: list[LongDSJudgement] = []
    for turn in prepared.turns:
        if turn_ids is not None and turn.turn_id not in turn_ids:
            continue
        path = capture / f"turn-{turn.turn_id:02}.response.json"
        if not path.is_file():
            continue
        http = json.loads((capture / f"turn-{turn.turn_id:02}.http.json").read_bytes())
        if not 200 <= http["status_code"] < 300:
            continue
        actual = ConversationTurnResponse.model_validate_json(path.read_bytes())
        if actual.disposition != "answer":
            continue
        ref = references[turn.turn_id - 1]
        result = judge.judge(output, turn_id=turn.turn_id, context=ref["context"], question=ref["question"],
                              answer=ref["answer"], solution=actual.message.content)
        results.append(result)
        if result.failure is not None:
            break
    report = JudgeScoreReport(configuration_digest=judge.configuration_digest,
        capture_checksums_sha256=sha256((capture / "checksums.json").read_bytes()).hexdigest(),
        qualification_checksums_sha256=sha256((qualification_directory / "checksums.json").read_bytes()).hexdigest(),
        task_turns=len(prepared.turns), turns=tuple(results),
        known_judge_tokens=judge.usage()[0], unknown_usage_attempts=judge.usage()[1])
    (output / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    seal(output)
    print(json.dumps({"task_turns": report.task_turns, "judged_turns": report.judged_turns,
                      "correct_turns": report.correct_turns, "known_judge_tokens": report.known_judge_tokens}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("qualify", "score"))
    parser.add_argument("--judge-root", type=Path, required=True)
    parser.add_argument("--source-directory", type=Path, required=True)
    parser.add_argument("--materials", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--name", default="l1-target")
    parser.add_argument("--turn-ids", nargs="+", type=int, choices=range(1, 51))
    args = parser.parse_args()
    judge = MeteredJudge(args.judge_root, source_directory=args.source_directory)
    try:
        if args.command == "qualify":
            qualify(judge, materials=args.materials, negative_capture=args.capture)
        else:
            score(judge, materials=args.materials, capture=args.capture, name=args.name, turn_ids=args.turn_ids)
    finally:
        judge.client.close()


if __name__ == "__main__":
    main()
