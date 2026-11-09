"""回放 task2 的完整真实决策输入；只观察初始提议，不代执行或代写分析。"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from personal_agent.application.conversation.interaction_prompt import build_requirements_context
from personal_agent.application.conversation.models import ReviewCriteria
from personal_agent.capabilities.contracts.model import (
    ModelActionDefinition,
    StructuredModelRequest,
    StructuredOutputFailure,
)
from personal_agent.infra.model_capacity import check_model_capacity
from personal_agent.infra.structured_model import OpenAIModelClient, _ProviderCompletion
from personal_agent.kernel.config import Settings
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .longds_materials import json_bytes, seal, verify_seal


Group = Literal["baseline", "position", "natural"]
SOURCE = Path(".tmp/ls25/t01/capture/sdk/2c3b5ebc2d57492cb8c4d0eb9d2b761a.candidate.request.json")
SOURCE_SHA256 = "bd47be4577b54b88771d79e250250dd6c628604101e1cb024cf3541b22e7bce3"


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Failure(Record):
    type: str
    message: str


class Proposal(Record):
    name: str
    program_path: str | None = None


class Sample(Record):
    index: int
    physical_requests: int
    retry_attempts: int
    proposals: tuple[Proposal, ...]
    visible_text_path: str
    error: Failure | None = None


class Report(Record):
    evidence_class: str = "offline_complete_actual_decision_stage"
    release_eligible: bool = False
    group: Group
    planned_samples: int = 10
    completed_samples: int
    unexecuted_samples: int
    samples: tuple[Sample, ...]
    physical_requests: int
    known_tokens: int
    unknown_usage_attempts: int
    wall_seconds: float
    new_tool_executions: int = 0
    failure: Failure | None = None


class Prepared(Record):
    source: str
    source_sha256: str
    model: str
    provider_host: str
    estimated_input_tokens: int
    max_output_tokens: int
    variants: tuple[Group, ...] = ("baseline", "position", "natural")
    samples_per_variant: int = 10
    max_physical_requests_per_variant: int = 20
    max_known_tokens_per_variant: int = 1_000_000
    max_wall_seconds_per_variant: int = 1800
    criteria: tuple[str, ...]
    production_requirements_version: str
    production_action_version: str


def _load(path: Path):
    return json.loads(path.read_bytes())


def _settings():
    settings = Settings.from_env().structured
    if (settings.model != "MiniMax-M3.1-Flash"
            or settings.extra_body != {"thinking": {"type": "adaptive"}, "reasoning_effort": "medium"}
            or settings.timeout_seconds != 480):
        raise ValueError("本次固定的模型、medium 或480秒超时配置发生变化")
    return settings


def _definitions(wire) -> tuple[ModelActionDefinition, ...]:
    definitions = []
    for item in wire["tools"]:
        function = item["function"]
        name = function["name"]
        kind = ("working_plan" if name == "control_working_plan" else
                "answer_result" if name.startswith("control_") else
                "agent" if name.startswith("agent_") else "tool")
        definitions.append(ModelActionDefinition(
            name=name, kind=kind, target_name=name.split("_", 1)[1],
            description=function["description"], input_schema=function["parameters"],
            strict=function.get("strict", True),
        ))
    return tuple(definitions)


def _request(wire, group: Group) -> StructuredModelRequest:
    return StructuredModelRequest(
        operation="agent_interaction_turn", version=f"requirements-context-{group}",
        messages=wire["messages"], output_type=BaseModel, kind="tool_calling",
        action_definitions=_definitions(wire), action_choice=wire["tool_choice"],
        max_tokens=wire["max_completion_tokens"], reasoning_effort=wire.get("reasoning_effort"),
        extra_body=wire.get("extra_body"),
        context_projection_ref="offline:task2-context:" + group + ":" + sha256(json_bytes(wire)).hexdigest(),
    )


def prepare(output: Path) -> None:
    if sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("真实阶段来源校验和失效")
    original = _load(SOURCE)
    text = original["messages"][0]["content"]
    label = "验收条件（JSON 数据）："
    begin = text.index("\n【任务与验收边界】")
    start = text.index(label)
    end = text.index("\n", start) + 1
    old_block = text[begin:end]
    criteria = ReviewCriteria(criteria=tuple(json.loads(text[start + len(label):end])))
    if not original["messages"][4]["content"].startswith("Typed execution inputs:\n"):
        raise ValueError("真实阶段的动态Context位置变化")
    settings = _settings()
    adapter = OpenAIModelClient(settings)
    if adapter._chat_kwargs(_request(original, "baseline")) != original:
        raise ValueError("基线经当前Model Port后未完整保持实际wire")
    variants = {"baseline": original}
    for group in ("position", "natural"):
        wire = deepcopy(original)
        wire["messages"][0]["content"] = text[:begin] + text[end:]
        wire["messages"][4]["content"] += (
            old_block if group == "position" else build_requirements_context(criteria)
        )
        if any(wire["messages"][i] != original["messages"][i] for i in (1, 2, 3, 5, 6)):
            raise ValueError("变量外的完整会话或原生历史被改变")
        variants[group] = wire
    capacity = check_model_capacity(
        operation="agent_interaction_turn", provider_host=urlparse(settings.base_url).hostname,
        model=settings.model, kwargs=original, capacity=settings.capacity,
    )
    prepared = Prepared(
        source=str(SOURCE), source_sha256=SOURCE_SHA256, model=settings.model,
        provider_host=urlparse(settings.base_url).hostname,
        estimated_input_tokens=capacity.estimated_input_tokens,
        max_output_tokens=original["max_completion_tokens"], criteria=criteria.criteria,
        production_requirements_version=DEFAULT_PROMPTS.get("conversation.requirements").version,
        production_action_version=DEFAULT_PROMPTS.get("conversation.action").version,
    )
    output.mkdir(parents=True, exist_ok=False)
    for group, wire in variants.items():
        (output / f"{group}.request.json").write_bytes(json_bytes(wire))
    (output / "preflight.json").write_text(prepared.model_dump_json(indent=2), encoding="utf-8")
    (output / "runner-source.py").write_bytes(Path(__file__).read_bytes())
    seal(output)
    print(prepared.model_dump_json(), flush=True)


def run(prepared_path: Path, output: Path, group: Group) -> None:
    verify_seal(prepared_path)
    prepared = Prepared.model_validate_json((prepared_path / "preflight.json").read_bytes())
    wire_path = prepared_path / f"{group}.request.json"
    wire = _load(wire_path)
    checksums = _load(prepared_path / "checksums.json")
    if sha256(wire_path.read_bytes()).hexdigest() != checksums[wire_path.name]:
        raise ValueError("回放请求校验和失效")
    output.mkdir(parents=True, exist_ok=False)
    started = monotonic()
    samples: list[Sample] = []
    failure = None

    class MeteredAdapter(OpenAIModelClient):
        calls = 0
        known = 0
        unknown = 0

        def _create_chat_completion(self, client, operation, kwargs, *, before_send=None) -> _ProviderCompletion:
            capacity = check_model_capacity(
                operation=operation, provider_host=self._provider_host, model=self._resolved_model,
                kwargs=kwargs, capacity=self._config.capacity,
            )
            if (self.calls >= prepared.max_physical_requests_per_variant or self.unknown
                    or monotonic() - started >= prepared.max_wall_seconds_per_variant
                    or self.known + capacity.estimated_input_tokens + capacity.output_reserve_tokens
                    > prepared.max_known_tokens_per_variant):
                raise RuntimeError("HTTP前触发已固定组级停止线")
            self.calls += 1
            number = self.calls
            (output / f"call-{number:02}.request.json").write_bytes(json_bytes(kwargs))
            try:
                result = super()._create_chat_completion(client, operation, kwargs, before_send=before_send)
            except Exception:
                self.unknown += 1
                raise
            payload = result.payload
            (output / f"call-{number:02}.response.json").write_text(payload.model_dump_json(indent=2), encoding="utf-8")
            usage = payload.usage
            if usage is None or any(getattr(usage, k) is None for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
                self.unknown += 1
                raise RuntimeError("服务未返回完整用量")
            self.known += usage.total_tokens
            if any(choice.finish_reason == "length" for choice in payload.choices):
                raise RuntimeError("响应截断；不补采样本")
            return result

    settings = _settings()
    if urlparse(settings.base_url or "").hostname != prepared.provider_host:
        raise ValueError("实际Provider端点与固定回放来源不一致")
    adapter = MeteredAdapter(settings)
    request = _request(wire, group)
    try:
        if adapter._chat_kwargs(request) != wire:
            raise ValueError("实际Model Port改变了固定回放请求")
        for index in range(1, prepared.samples_per_variant + 1):
            before = adapter.calls
            error = None
            try:
                response = adapter.generate(request)
            except StructuredOutputFailure as exc:
                if exc.response is None:
                    raise
                response = exc.response
                error = Failure(type=type(exc).__name__, message=str(exc))
            proposals = []
            for action_index, action in enumerate(response.action_invocations, start=1):
                code = None
                if action.name == "tool_write_artifact":
                    proposed = action.arguments.get("request", {})
                    if proposed.get("content_type") == "text/x-python" or str(proposed.get("filename", "")).endswith(".py"):
                        code = proposed.get("content")
                elif action.name == "tool_execute_python":
                    code = action.arguments.get("code")
                path = None
                if isinstance(code, str):
                    path = f"sample-{index:02}-program-{action_index:02}.py"
                    (output / path).write_text(code, encoding="utf-8")
                proposals.append(Proposal(name=action.name, program_path=path))
            text_path = f"sample-{index:02}-visible.txt"
            (output / text_path).write_text(
                response.assistant_message.visible_text or "" if response.assistant_message else "", encoding="utf-8",
            )
            sample = Sample(index=index, physical_requests=adapter.calls - before,
                            retry_attempts=response.retry_attempts, proposals=tuple(proposals),
                            visible_text_path=text_path, error=error)
            samples.append(sample)
            (output / f"sample-{index:02}.json").write_text(sample.model_dump_json(indent=2), encoding="utf-8")
            print(f"{group} {index}/10; physical={adapter.calls}; known_tokens={adapter.known}", flush=True)
    except Exception as exc:
        failure = Failure(type=type(exc).__name__, message=str(exc))
    finally:
        report = Report(group=group, completed_samples=len(samples), unexecuted_samples=10 - len(samples),
                        samples=tuple(samples), physical_requests=adapter.calls, known_tokens=adapter.known,
                        unknown_usage_attempts=adapter.unknown, wall_seconds=monotonic() - started, failure=failure)
        (output / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        (output / "runner-source.py").write_bytes(Path(__file__).read_bytes())
        seal(output)
        print(report.model_dump_json(exclude={"samples"}), flush=True)
    if failure:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--group", choices=("baseline", "position", "natural"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output)
    elif args.prepared is None or args.group is None:
        parser.error("run requires --prepared and --group")
    else:
        run(args.prepared, args.output, args.group)


if __name__ == "__main__":
    main()
