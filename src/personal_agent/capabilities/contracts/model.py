"""Provider-neutral model invocation protocol contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Generic, Iterator, Literal, Protocol, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)
ModelRequestKind = Literal[
    "structured",
    "tool_calling",
    "text",
]
ModelReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh"]
ModelActionKind = Literal["tool", "agent", "working_plan", "finalize"]
ModelInvocationFailureCategory = Literal[
    "provider_rejected",
    "provider_timeout",
    "provider_transport",
]
StructuredOutputFailureCode = Literal[
    "structured_output_invalid",
    "provider_action_missing",
    "provider_action_type_unsupported",
    "provider_action_call_id_missing",
    "provider_action_call_id_duplicate",
    "provider_action_unknown",
    "provider_action_arguments_invalid_json",
    "provider_action_arguments_not_object",
    "provider_action_working_plan_payload_invalid",
    "provider_action_tool_payload_invalid",
    "provider_action_agent_payload_invalid",
    "provider_action_finalize_payload_invalid",
    "provider_action_multiple_working_plans",
    "provider_action_definition_invalid",
]


class ModelActionDefinition(BaseModel):
    """One provider-neutral action exposed to a model for this invocation.

    ``name`` is the provider-safe wire identity. ``target_name`` remains the
    canonical Application capability or control identity and is never accepted
    from the model. The Adapter consumes the definition to build provider tool
    declarations; the Application consumes the same immutable definition to
    decode the selected wire name without maintaining a second registry.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    kind: ModelActionKind
    target_name: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, Any]

    @model_validator(mode="after")
    def _requires_object_input(self) -> "ModelActionDefinition":
        if self.input_schema.get("type") != "object":
            raise ValueError("model action input_schema must have an object root")
        return self


class ModelActionInvocation(BaseModel):
    """A structurally validated provider action call at the model Port boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str = Field(min_length=1)
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    arguments: dict[str, Any]


class ModelInvocationUnavailable(RuntimeError):
    """A model call could not produce a usable provider response.

    This is a framework-boundary error: infra adapters may attach diagnostic
    facts, while application code should expose only a stable user-facing
    failure. ``provider_host`` is intentionally host-only so credentials and
    raw provider payloads cannot cross the boundary.
    """

    def __init__(
        self,
        operation: str,
        category: ModelInvocationFailureCategory,
        *,
        model: str | None = None,
        provider_host: str | None = None,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        self.operation = operation
        self.category = category
        self.model = model
        self.provider_host = provider_host
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(f"{operation} model provider unavailable ({category})")


class StructuredOutputFailure(ValueError):
    """The provider returned content that failed the typed output contract."""

    def __init__(
        self,
        operation: str,
        reason: str,
        *,
        reason_code: StructuredOutputFailureCode = "structured_output_invalid",
        action_name: str | None = None,
        action_kind: ModelActionKind | None = None,
        field_paths: tuple[str, ...] = (),
        error_types: tuple[str, ...] = (),
    ) -> None:
        if len(field_paths) != len(error_types):
            raise ValueError("structured output diagnostic fields must align")
        self.operation = operation
        self.reason = reason
        self.reason_code = reason_code
        self.action_name = action_name
        self.action_kind = action_kind
        self.field_paths = field_paths
        self.error_types = error_types
        super().__init__(f"{operation} structured parse failed: {reason}")


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
    action_definitions: tuple[ModelActionDefinition, ...] = ()
    action_choice: Literal["none", "auto", "required"] | None = None
    response_format: dict[str, object] | None = None
    extra_body: dict[str, object] | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.context_projection_ref.strip():
            raise ValueError("model request requires an explicit context projection reference")
        if self.context_projection_ref.startswith("inline:"):
            raise ValueError("inline model context bypass is forbidden")
        action_names = [item.name for item in self.action_definitions]
        if len(action_names) != len(set(action_names)):
            raise ValueError("model action definitions require unique wire names")
        if self.kind == "tool_calling" and not self.action_definitions:
            raise ValueError("action-capable request requires model action definitions")
        if self.kind != "tool_calling" and (
            self.action_definitions or self.action_choice is not None
        ):
            raise ValueError(
                "model action definitions and choice are valid only for tool-calling requests"
            )


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
    action_invocations: tuple[ModelActionInvocation, ...] = ()
    retry_attempts: int = 0
    retry_errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.value is not None and self.action_invocations:
            raise ValueError(
                "model response cannot contain both typed output and action invocations"
            )


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
    "ModelActionDefinition", "ModelActionInvocation", "ModelActionKind",
    "ModelCallIntent", "ModelInvocationDenial", "ModelInvocationGrant", "ModelReasoningEffort",
    "ModelInvocationFailureCategory", "ModelInvocationUnavailable",
    "StructuredOutputFailure", "StructuredOutputFailureCode",
    "ModelRequestKind",
    "SkillActivationDecision", "SkillContextGrant", "StreamChunk", "StreamingModelClient",
    "StructuredModelClient", "StructuredModelRequest", "StructuredModelResponse", "StructuredOutputT",
    "sealed_context_projection_ref",
]
