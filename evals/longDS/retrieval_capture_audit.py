"""读取公开 LongDS 采集的 SDK 与 HTTP 原件，按真实派发计量。"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.python_execution.models import Digest
from personal_agent.capabilities.contracts.model import (
    ModelTransportDiagnostics, ProviderExceptionFrame, ProviderFailureDiagnostics,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ObservedProviderUsage(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ObservedProviderMessage(BaseModel):
    """Unmodified external SDK message; usage audit does not certify its role."""
    model_config = ConfigDict(extra="allow", frozen=True)
    role: str
    content: str | None = None


class ObservedProviderChoice(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    index: int
    finish_reason: str | None = None
    message: ObservedProviderMessage


class ObservedProviderCompletion(BaseModel):
    """Provider 拥有的完整响应；用量字段缺失时仍保留其余真实内容。"""
    model_config = ConfigDict(extra="allow", frozen=True)
    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    choices: tuple[ObservedProviderChoice, ...]
    usage: ObservedProviderUsage | None = None


class SdkResponseObservation(_Strict):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    observation: Literal["before_capacity_admission"]
    operation: str
    completed: bool
    candidate_body_sha256: Digest | None = None
    response: ObservedProviderCompletion | None = None
    exception_type: str | None = None
    provider_diagnostics: ProviderFailureDiagnostics | None = None
    reason_code: str | None = None
    body_observation_error: str | None = None
    wall_seconds: float = Field(ge=0, allow_inf_nan=False)


class HttpSendObservation(_Strict):
    send_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    observation: Literal["httpx_client_send_invoked"]
    candidate_ids_on_client: tuple[str, ...]
    provider_host: str
    method: str
    path: str
    response_received: bool
    request_body_sha256: Digest | None = None
    request_body_bytes: int | None = Field(default=None, ge=0)
    status_code: int | None = None
    exception_type: str | None = None
    exception_chain: tuple[ProviderExceptionFrame, ...] = ()
    transport: ModelTransportDiagnostics | None = None
    body_observation_error: str | None = None
    wall_seconds: float = Field(ge=0, allow_inf_nan=False)


class WireUsageGroup(_Strict):
    wire_value_sha256: Digest
    http_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    complete_sdk_responses: int = Field(ge=0)
    known_tokens: int = Field(ge=0)
    unknown_usage_attempts: int = Field(ge=0)
    missing_http_response_sidecars: tuple[str, ...]


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return sha256(_json_bytes(value)).hexdigest()


def _load(path: Path):
    return json.loads(path.read_bytes())


def _wire_groups(directory: Path) -> tuple[tuple[WireUsageGroup, ...], int]:
    """匹配 JSON 值；不把重新序列化的值摘要冒充实际 HTTP bytes 摘要。"""
    candidates: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(directory.glob("*.candidate.request.json")):
        kwargs = _load(path)
        wire = {key: value for key, value in kwargs.items() if key != "extra_body"}
        wire.update(kwargs.get("extra_body") or {})
        candidates[_digest(wire)].append(path)
    http: dict[str, list[Path]] = defaultdict(list)
    body_ids = {path.name.split(".")[0] for path in directory.glob("*.http.request.json")}
    response_ids = {path.name.split(".")[0] for path in directory.glob("*.http.response.json")}
    if response_ids - body_ids:
        raise ValueError("实际 HTTP send 缺完整 body；须保留未知并另审观察失败，不能少计物理请求")
    for path in sorted(directory.glob("*.http.request.json")):
        http[_digest(_load(path))].append(path)
    groups = []
    for digest, paths in http.items():
        matching = candidates.get(digest, [])
        if not matching:
            raise ValueError("实际 HTTP body 无对应 SDK kwargs，不能推测其归属或费用")
        complete = full_usage = known = 0
        for candidate in matching:
            response = candidate.with_name(candidate.name.replace(".request.json", ".response.json"))
            if not response.is_file():
                continue
            record = SdkResponseObservation.model_validate_json(response.read_bytes())
            if (record.candidate_id != candidate.name.split(".")[0]
                    or record.candidate_body_sha256 != sha256(candidate.read_bytes()).hexdigest()
                    or record.body_observation_error):
                raise ValueError("SDK 观察与候选原件不一致或观察失败")
            if not record.completed:
                continue
            actual = record.response
            if actual is None:
                raise ValueError("SDK completed 缺实际响应")
            complete += 1
            if actual.usage is not None:
                if actual.usage.total_tokens is not None:
                    known += actual.usage.total_tokens
                if all(value is not None for value in (actual.usage.prompt_tokens,
                       actual.usage.completion_tokens, actual.usage.total_tokens)):
                    full_usage += 1
        if complete > len(paths):
            raise ValueError("完整 SDK 响应数超过同 body 的真实物理发送，观察身份不成立")
        missing = []
        for path in paths:
            sidecar = path.with_name(path.name.replace(".request.json", ".response.json"))
            identity = path.name.split(".")[0]
            if not sidecar.is_file():
                missing.append(identity)
                continue
            observation = HttpSendObservation.model_validate_json(sidecar.read_bytes())
            if (observation.send_id != identity
                    or observation.request_body_sha256 != sha256(path.read_bytes()).hexdigest()
                    or observation.body_observation_error):
                raise ValueError("实际 HTTP sidecar 与原 body 不一致或观察失败")
        groups.append(WireUsageGroup(
            wire_value_sha256=digest, http_ids=tuple(path.name.split(".")[0] for path in paths),
            candidate_ids=tuple(path.name.split(".")[0] for path in matching), complete_sdk_responses=complete,
            known_tokens=known, unknown_usage_attempts=len(paths) - full_usage,
            missing_http_response_sidecars=tuple(missing)))
    for digest, paths in candidates.items():
        if digest in http:
            continue
        for path in paths:
            response = path.with_name(path.name.replace(".request.json", ".response.json"))
            if response.is_file() and SdkResponseObservation.model_validate_json(response.read_bytes()).completed:
                raise ValueError("完整 SDK 响应没有真实 HTTP 观察，不能宣称物理费用完整")
    return tuple(groups), sum(len(paths) for paths in candidates.values())
