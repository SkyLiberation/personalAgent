"""Provider-neutral model invocation protocol contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Generic, Iterator, Literal, Protocol, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field

StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)
ModelRequestKind = Literal["structured", "tool_calling", "text"]
ModelReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh"]


@dataclass(frozen=True, slots=True)
class StructuredModelRequest(Generic[StructuredOutputT]):
    operation: str
    version: str
    messages: list[dict[str, Any]]
    output_type: type[StructuredOutputT]
    context_projection_ref: str
    sensitivity: Literal["public", "internal", "confidential", "restricted"] = "internal"
    temperature: float = 0
    max_tokens: int = 500
    reasoning_effort: ModelReasoningEffort | None = None
    kind: ModelRequestKind = "structured"
    tools: list[dict[str, object]] = field(default_factory=list)
    tool_choice: str | dict[str, object] | None = None
    response_format: dict[str, object] | None = None
    extra_body: dict[str, object] | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.context_projection_ref.strip():
            raise ValueError("model request requires an explicit context projection reference")
        if self.context_projection_ref.startswith("inline:"):
            raise ValueError("inline model context bypass is forbidden")


def sealed_context_projection_ref(
    *,
    purpose: str,
    messages: list[dict[str, Any]],
) -> str:
    """Create a content-addressed ref for an already bounded service context.

    Agent-runtime calls should use the audited ``ContextProjection.projection_id``.
    This seal is for bounded application services whose complete input is the
    message list itself; changing any visible input creates a different ref.
    """
    canonical = json.dumps(
        {"purpose": purpose, "messages": messages},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sealed-context:v1:{digest}"


@dataclass(frozen=True, slots=True)
class StructuredModelResponse(Generic[StructuredOutputT]):
    value: StructuredOutputT
    model: str
    latency_ms: float
    content: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    raw_response: Any = None
    tool_calls: list[dict[str, Any]] | None = None
    retry_attempts: int = 0
    retry_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class StreamChunk:
    delta: str
    accumulated: str
    usage: dict[str, int] | None = None


class StructuredModelClient(Protocol):
    def generate(
        self,
        request: StructuredModelRequest[StructuredOutputT],
    ) -> StructuredModelResponse[StructuredOutputT]: ...


class StreamingModelClient(Protocol):
    def stream(self, request: StructuredModelRequest[Any]) -> Iterator[StreamChunk]: ...


class ModelCallIntent(BaseModel):
    call_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    purpose: str
    operation: str
    context_projection_ref: str
    sensitivity: Literal["public", "internal", "confidential", "restricted"] = "internal"
    structured_output_contract: str
    max_input_tokens: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)


class SkillActivationDecision(BaseModel):
    call_id: str
    activated_skill_refs: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    policy_revision: str = "v1"


class SkillContextGrant(BaseModel):
    grant_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    call_id: str
    skill_refs: tuple[str, ...] = ()
    context_item_refs: tuple[str, ...] = ()
    expires_after_call: bool = True


class ModelInvocationGrant(BaseModel):
    grant_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    call_id: str
    purpose: str
    provider: str
    model: str
    region: str | None = None
    allowed_egress: Literal["none", "metadata", "content", "sensitive"] = "content"
    context_projection_ref: str
    max_input_tokens: int
    max_output_tokens: int
    policy_revision: str = "v1"


class ModelInvocationDenial(BaseModel):
    call_id: str
    reason_code: str
    message: str


__all__ = [
    "ModelCallIntent", "ModelInvocationDenial", "ModelInvocationGrant", "ModelReasoningEffort",
    "ModelRequestKind",
    "SkillActivationDecision", "SkillContextGrant", "StreamChunk", "StreamingModelClient",
    "StructuredModelClient", "StructuredModelRequest", "StructuredModelResponse", "StructuredOutputT",
    "sealed_context_projection_ref",
]
