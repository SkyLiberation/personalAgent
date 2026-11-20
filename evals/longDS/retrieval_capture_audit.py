"""读取公开 LongDS 采集的 SDK 与 HTTP 原件，按真实派发计量。"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.bash_execution.models import Digest
from personal_agent.capabilities.contracts.model import (
    ModelTransportDiagnostics, ProviderExceptionFrame, ProviderFailureDiagnostics,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ObservedPromptTokenDetails(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    cached_tokens: int | None = Field(default=None, ge=0)
    cache_write_tokens: int | None = Field(default=None, ge=0)


class ObservedProviderUsage(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    prompt_tokens_details: ObservedPromptTokenDetails | None = None
    prompt_cache_hit_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)

    @property
    def known_tokens(self) -> int:
        if self.total_tokens is not None:
            return self.total_tokens
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)

    @property
    def cache_read_tokens(self) -> int | None:
        if self.prompt_tokens_details is not None and self.prompt_tokens_details.cached_tokens is not None:
            return self.prompt_tokens_details.cached_tokens
        if self.prompt_cache_hit_tokens is not None:
            return self.prompt_cache_hit_tokens
        return self.cached_tokens

    @property
    def cache_write_tokens(self) -> int | None:
        return self.prompt_tokens_details.cache_write_tokens if self.prompt_tokens_details is not None else None

    @property
    def cache_miss_input_tokens(self) -> int | None:
        cached = self.cache_read_tokens
        if cached is None or self.prompt_tokens is None or cached > self.prompt_tokens:
            return None
        return self.prompt_tokens - cached

    @property
    def uncached_input_tokens(self) -> int | None:
        outside_cache_read = self.cache_miss_input_tokens
        # Pi-AI uses zero for unreported writes when normalizing input.
        cache_write = self.cache_write_tokens or 0
        if outside_cache_read is None or cache_write > outside_cache_read:
            return None
        return outside_cache_read - cache_write


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


class KnownTokenSubtotal(_Strict):
    """Sum over attempts reporting this field. No observations means unknown."""

    tokens: int | None = Field(ge=0)
    observed_attempts: int = Field(ge=0)

    @classmethod
    def from_samples(cls, values: Iterable[int | None]) -> KnownTokenSubtotal:
        observed = [value for value in values if value is not None]
        return cls(tokens=sum(observed) if observed else None, observed_attempts=len(observed))


class GenerationTokenBreakdown(_Strict):
    input_tokens: KnownTokenSubtotal
    output_tokens: KnownTokenSubtotal
    cache_read_tokens: KnownTokenSubtotal
    cache_write_tokens: KnownTokenSubtotal
    cache_miss_input_tokens: KnownTokenSubtotal
    uncached_input_tokens: KnownTokenSubtotal | None = None
    cache_hit_rate: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)

    @classmethod
    def from_samples(cls, samples: list[ObservedProviderUsage]) -> GenerationTokenBreakdown:
        paired_inputs = 0
        paired_cache_reads = 0
        misses: list[int] = []
        for usage in samples:
            prompt_tokens = usage.prompt_tokens
            miss = usage.cache_miss_input_tokens
            if prompt_tokens is not None and miss is not None:
                paired_inputs += prompt_tokens
                paired_cache_reads += prompt_tokens - miss
                misses.append(miss)
        return cls(
            input_tokens=KnownTokenSubtotal.from_samples(usage.prompt_tokens for usage in samples),
            output_tokens=KnownTokenSubtotal.from_samples(usage.completion_tokens for usage in samples),
            cache_read_tokens=KnownTokenSubtotal.from_samples(usage.cache_read_tokens for usage in samples),
            cache_write_tokens=KnownTokenSubtotal.from_samples(usage.cache_write_tokens for usage in samples),
            cache_miss_input_tokens=KnownTokenSubtotal.from_samples(misses),
            uncached_input_tokens=KnownTokenSubtotal.from_samples(usage.uncached_input_tokens for usage in samples),
            cache_hit_rate=paired_cache_reads / paired_inputs if paired_inputs else None,
        )


class GenerationUsage(_Strict):
    physical_model_requests: int = Field(ge=0)
    known_tokens: int = Field(ge=0)
    unknown_usage_attempts: int = Field(ge=0)
    token_breakdown: GenerationTokenBreakdown

    def reaches_case_limit(self, limit: int, *, preceding_known_tokens: int) -> bool:
        return preceding_known_tokens + self.known_tokens >= limit


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return sha256(_json_bytes(value)).hexdigest()


def _load(path: Path):
    return json.loads(path.read_bytes())


def read_generation_usage(directory: Path) -> GenerationUsage:
    """Fold complete responses once per physical attempt, including protocol retries."""
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
    samples: list[ObservedProviderUsage] = []
    for digest, paths in http.items():
        matching = candidates.get(digest, [])
        if not matching:
            raise ValueError("实际 HTTP body 无对应 SDK kwargs，不能推测其归属或费用")
        complete = 0
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
                samples.append(actual.usage)
        if complete > len(paths):
            raise ValueError("完整 SDK 响应数超过同 body 的真实物理发送，观察身份不成立")
        for path in paths:
            sidecar = path.with_name(path.name.replace(".request.json", ".response.json"))
            identity = path.name.split(".")[0]
            if not sidecar.is_file():
                continue
            observation = HttpSendObservation.model_validate_json(sidecar.read_bytes())
            if (observation.send_id != identity
                    or observation.request_body_sha256 != sha256(path.read_bytes()).hexdigest()
                    or observation.body_observation_error):
                raise ValueError("实际 HTTP sidecar 与原 body 不一致或观察失败")
    for digest, paths in candidates.items():
        if digest in http:
            continue
        for path in paths:
            response = path.with_name(path.name.replace(".request.json", ".response.json"))
            if response.is_file() and SdkResponseObservation.model_validate_json(response.read_bytes()).completed:
                raise ValueError("完整 SDK 响应没有真实 HTTP 观察，不能宣称物理费用完整")
    full_usage = sum(item.prompt_tokens is not None and item.completion_tokens is not None for item in samples)
    return GenerationUsage(
        physical_model_requests=len(body_ids),
        known_tokens=sum(item.known_tokens for item in samples),
        unknown_usage_attempts=len(body_ids) - full_usage,
        token_breakdown=GenerationTokenBreakdown.from_samples(samples),
    )
