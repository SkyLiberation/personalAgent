"""LongDS 独立评分配置及无凭据的实际请求身份。"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
import os
from typing import Literal
from urllib.parse import urlparse

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, JsonValue, SecretStr, TypeAdapter, model_validator

from personal_agent.application.python_execution.models import Digest
from personal_agent.infra.model_providers import build_provider_policy
from personal_agent.kernel.config_models import ModelCapacityConfig
from personal_agent.kernel.model_provider import ModelProvider, resolve_model_provider


PROMPT_SHA256 = "07844fdda634dcbb492e2ad2a9a5969cb3707de8f8b8c00c22d9817b320d2816"
JUDGE_SOURCE_SHA256 = "80ea064624368ca74ef9a7f900e1ff2ef423fd8ff5ca401dcb349d97bda2c9c6"
TOKEN_LIMIT = 2_000_000
OUTPUT_LIMIT = 32_768


class LongDSJudgeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: ModelProvider
    model: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    api_key: SecretStr = Field(exclude=True, repr=False)
    extra_body: dict[str, JsonValue]
    max_output_tokens: int = Field(default=OUTPUT_LIMIT, gt=0)
    timeout_seconds: float = Field(default=480, gt=0, allow_inf_nan=False)
    model_capacity: ModelCapacityConfig | None = None

    @model_validator(mode="after")
    def bind_endpoint_and_capacity(self) -> LongDSJudgeSettings:
        endpoint = TypeAdapter(AnyHttpUrl).validate_python(self.base_url)
        if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ValueError("评分端点不得包含凭据、query或fragment")
        if not self.api_key.get_secret_value().strip():
            raise ValueError("缺少LongDS独立评分凭据")
        object.__setattr__(self, "base_url", str(endpoint).rstrip("/") + "/")
        resolve_model_provider(self.base_url, self.provider)
        if self.model_capacity is not None:
            capacity = self.model_capacity
            if capacity.model != self.model or capacity.provider_host != urlparse(self.base_url).hostname:
                raise ValueError("评分容量配置必须绑定实际模型和端点host")
            if self.max_output_tokens > capacity.max_output_tokens:
                raise ValueError("评分请求输出超过已声明的模型输出容量")
        return self

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> LongDSJudgeSettings:
        env = os.environ if environ is None else environ
        required = ("PROVIDER", "MODEL", "BASE_URL", "API_KEY", "EXTRA_BODY")
        missing = ["LONGDS_JUDGE_" + name for name in required if not env.get("LONGDS_JUDGE_" + name, "").strip()]
        if missing:
            raise ValueError("缺少独立评分配置：" + ", ".join(missing))
        capacity = env.get("LONGDS_JUDGE_MODEL_CAPACITY")
        return cls(
            provider=env["LONGDS_JUDGE_PROVIDER"].strip(),
            model=env["LONGDS_JUDGE_MODEL"].strip(),
            base_url=env["LONGDS_JUDGE_BASE_URL"].strip(),
            api_key=SecretStr(env["LONGDS_JUDGE_API_KEY"]),
            extra_body=TypeAdapter(dict[str, JsonValue]).validate_json(env["LONGDS_JUDGE_EXTRA_BODY"]),
            max_output_tokens=env.get("LONGDS_JUDGE_MAX_OUTPUT_TOKENS", str(OUTPUT_LIMIT)),
            timeout_seconds=env.get("LONGDS_JUDGE_TIMEOUT_SECONDS", "480"),
            model_capacity=ModelCapacityConfig.model_validate_json(capacity) if capacity else None,
        )


class JudgeConfiguration(BaseModel):
    """由同一评分设置派生的只读归档；不保存API key。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: ModelProvider
    provider_host: str = Field(min_length=1)
    endpoint_sha256: Digest
    model: str = Field(min_length=1)
    extra_body: dict[str, JsonValue]
    # 外部SDK拥有参数名；记录Policy实际投影，供请求原样消费。
    request_parameters: dict[str, JsonValue]
    model_capacity: ModelCapacityConfig | None = None
    prompt_sha256: Digest = PROMPT_SHA256
    source_sha256: Digest = JUDGE_SOURCE_SHA256
    request_projection: Literal["provider-policy-v1"] = "provider-policy-v1"
    max_output_tokens: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    sdk_max_retries: Literal[0] = 0
    protocol_attempts: Literal[3] = 3
    total_token_limit: int = Field(default=TOKEN_LIMIT, gt=0)

    @property
    def digest(self) -> Digest:
        serialized = json.dumps(self.model_dump(mode="json"), ensure_ascii=False,
                                sort_keys=True, separators=(",", ":"), allow_nan=False)
        return sha256(serialized.encode("utf-8")).hexdigest()


def build_judge_configuration(settings: LongDSJudgeSettings, *, total_token_limit: int = TOKEN_LIMIT) -> JudgeConfiguration:
    policy = build_provider_policy(base_url=settings.base_url, provider=settings.provider)
    parameters = policy.prepare_chat_parameters(
        {"model": settings.model, "max_tokens": settings.max_output_tokens},
        defaults=settings.extra_body,
    )
    return JudgeConfiguration(
        provider=settings.provider,
        provider_host=urlparse(settings.base_url).hostname or "",
        endpoint_sha256=sha256(settings.base_url.encode("utf-8")).hexdigest(),
        model=settings.model,
        extra_body=settings.extra_body,
        request_parameters=parameters,
        model_capacity=settings.model_capacity,
        max_output_tokens=settings.max_output_tokens,
        timeout_seconds=settings.timeout_seconds,
        total_token_limit=total_token_limit,
    )
