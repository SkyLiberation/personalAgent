"""Provider-neutral model invocation protocol contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Literal, Protocol, TypedDict, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)
ModelRequestKind = Literal[
    "structured",
    "tool_calling",
    "text",
]
ModelReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh"]
ModelOutputTransport = Literal["native_tool", "prompted_json"]
ModelActionKind = Literal["tool", "agent", "working_plan", "answer_result"]
ModelInvocationFailureCategory = Literal[
    "provider_rejected",
    "provider_timeout",
    "provider_transport",
]
PROVIDER_DIAGNOSTIC_MAX_CHARS = 512
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
    "provider_action_answer_result_payload_invalid",
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
    strict: bool = True

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


class ModelAssistantMessage(BaseModel):
    """Provider-owned assistant JSON, bound to the provider that can consume it."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    provider_host: str = Field(min_length=1)
    model: str = Field(min_length=1)
    payload: dict[str, Any]

    @model_validator(mode="after")
    def _valid_pairing_identity(self):
        if self.payload.get("role") != "assistant":
            raise ValueError("native history requires the original assistant role")
        calls = self.payload.get("tool_calls")
        if calls is None:
            calls = []
        if not isinstance(calls, list) or any(
            not isinstance(call, dict) or not isinstance(call.get("id"), str)
            or not call["id"] for call in calls
        ):
            raise ValueError("native history requires actual nonempty tool call IDs")
        if len(set(self.call_ids)) != len(self.call_ids):
            raise ValueError("native history tool call IDs must be unique")
        return self

    @property
    def call_ids(self) -> tuple[str, ...]:
        return tuple(call["id"] for call in self.payload.get("tool_calls") or [])

    @property
    def visible_text(self) -> str | None:
        """The provider's exact visible text, independent of reasoning fields."""
        content = self.payload.get("content")
        return content if isinstance(content, str) else None


class ModelToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    call_id: str = Field(min_length=1)
    content: str


class ModelToolExchange(BaseModel):
    """A complete protocol exchange; tool content is a projection, not authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    assistant: ModelAssistantMessage
    results: tuple[ModelToolResult, ...] = ()

    @model_validator(mode="after")
    def _complete_pairing(self):
        if tuple(result.call_id for result in self.results) != self.assistant.call_ids:
            raise ValueError("native exchange must pair every call in original order")
        return self


class ProviderExceptionFrame(BaseModel):
    """One bounded cause/context frame; messages exclude HTTP error bodies."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_max_length=PROVIDER_DIAGNOSTIC_MAX_CHARS)

    relation: Literal["root", "cause", "context"]
    exception_type: str
    message: str | None = None


class ModelTransportDiagnostics(BaseModel):
    """Request-local HTTP observations, independent of model usage or success."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_max_length=PROVIDER_DIAGNOSTIC_MAX_CHARS)

    attempt_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    provider_host: str
    phase: str | None = None
    failure_phase: str | None = None
    status_code: int | None = None
    headers_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    first_byte_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    last_byte_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    elapsed_seconds: float = Field(ge=0, allow_inf_nan=False)
    body_bytes: int = Field(default=0, ge=0)
    body_chunks: int = Field(default=0, ge=0)
    body_complete: bool = False
    closed: bool = False
    content_type: str | None = None
    content_length: str | None = None
    transfer_encoding: str | None = None
    content_encoding: str | None = None
    provider_request_id: str | None = None
    retry_after: str | None = None
    connect_host: str | None = None
    connect_port: int | None = Field(default=None, ge=0, le=65535)
    peer_host: str | None = None
    peer_port: int | None = Field(default=None, ge=0, le=65535)


class ProviderFailureDiagnostics(BaseModel):
    """Bounded, redacted provider facts for internal failure observability."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_max_length=PROVIDER_DIAGNOSTIC_MAX_CHARS,
    )

    error_code: str | None = None
    error_type: str | None = None
    message: str | None = None
    request_id: str | None = None
    retry_after: str | None = None
    exception_chain: tuple[ProviderExceptionFrame, ...] = Field(default=(), max_length=8)
    transport: ModelTransportDiagnostics | None = None


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
        diagnostics: ProviderFailureDiagnostics | None = None,
        provider_response_complete: bool = False,
    ) -> None:
        self.operation = operation
        self.category = category
        self.model = model
        self.provider_host = provider_host
        self.status_code = status_code
        self.retryable = retryable
        self.diagnostics = diagnostics
        # A complete rejected ChatCompletion can carry actual usage. This does
        # not assert usage fields are present, nor that the request succeeded.
        self.provider_response_complete = provider_response_complete
        # Completed responses before a later transport failure remain billable.
        self.response: "StructuredModelResponse[Any] | None" = None
        self.prior_responses: tuple[StructuredModelResponse[Any], ...] = ()
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
        # A rejected provider response remains an observed, billable call.
        # Only the adapter attaches this; it contains no admitted actions.
        self.response: "StructuredModelResponse[Any] | None" = None
        self.prior_responses: tuple[StructuredModelResponse[Any], ...] = ()
        super().__init__(f"{operation} structured parse failed: {reason}")


class ModelCapacityCheck(BaseModel):
    """Estimated final wire-body capacity, without changing its content."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    operation: str
    provider_host: str
    model: str
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    estimator_version: Literal["ascii_json_bytes_v1"] = "ascii_json_bytes_v1"
    measurement_kind: Literal["estimated"] = "estimated"
    serialized_body_bytes: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)
    requested_output_tokens: int | None
    output_reserve_tokens: int = Field(gt=0)
    protocol_reserve_tokens: int = Field(ge=0)
    context_window_tokens: int = Field(gt=0)


class ModelCapacityRefused(ValueError):
    """A local deterministic refusal; completed earlier responses stay billable."""

    def __init__(
        self,
        operation: str,
        reason_code: Literal[
            "context_capacity_exceeded",
            "output_capacity_exceeded",
            "capacity_profile_mismatch",
            "capacity_payload_unsupported",
        ],
        *,
        check: ModelCapacityCheck | None = None,
    ) -> None:
        self.operation = operation
        self.reason_code = reason_code
        self.check = check
        self.response: StructuredModelResponse[Any] | None = None
        self.prior_responses: tuple[StructuredModelResponse[Any], ...] = ()
        super().__init__(f"{operation} model capacity refused ({reason_code})")


@dataclass(frozen=True, slots=True)
class StructuredModelRequest(Generic[StructuredOutputT]):
    operation: str
    version: str
    messages: list[dict[str, Any]]
    output_type: type[StructuredOutputT]
    context_projection_ref: str
    consumer_key: str | None = None
    sensitivity: Literal["public", "internal", "confidential", "restricted"] = (
        "internal"
    )
    temperature: float = 0
    # None delegates the output limit to the provider's model default.
    max_tokens: int | None = None
    reasoning_effort: ModelReasoningEffort | None = None
    kind: ModelRequestKind = "structured"
    action_definitions: tuple[ModelActionDefinition, ...] = ()
    action_choice: Literal["none", "auto", "required"] | None = None
    response_format: dict[str, object] | None = None
    output_transport: ModelOutputTransport | None = None
    extra_body: dict[str, object] | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    max_output_repairs: int = 1
    model_history: tuple[ModelToolExchange, ...] = ()

    def __post_init__(self) -> None:
        if self.consumer_key is not None and (not isinstance(self.consumer_key, str) or not self.consumer_key.strip()):
            raise ValueError("model consumer key must be a nonempty Runtime binding")
        if self.max_output_repairs < 0:
            raise ValueError("output repair budget must be nonnegative")
        if self.output_transport not in (None, "native_tool", "prompted_json"):
            raise ValueError("unsupported structured output transport")
        if not self.context_projection_ref.strip():
            raise ValueError(
                "model request requires an explicit context projection reference"
            )
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
        if self.output_transport is not None and (
            self.kind != "structured"
            or self.response_format is not None
            or self.action_definitions
            or self.action_choice is not None
        ):
            raise ValueError(
                "explicit output transport requires a structured request without "
                "response_format or business action definitions"
            )


def model_request_digest(request: StructuredModelRequest[Any]) -> str:
    """Bind continuation to the complete original typed invocation contract."""
    canonical = json.dumps(
        {
            "operation": request.operation,
            "version": request.version,
            "messages": request.messages,
            "output_type": (
                f"{request.output_type.__module__}.{request.output_type.__qualname__}"
                if request.kind == "structured" else None
            ),
            "output_schema": (
                request.output_type.model_json_schema()
                if request.kind == "structured" else None
            ),
            "context_projection_ref": request.context_projection_ref,
            "consumer_key": request.consumer_key,
            "sensitivity": request.sensitivity,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "reasoning_effort": request.reasoning_effort,
            "kind": request.kind,
            "action_definitions": [
                item.model_dump(mode="json") for item in request.action_definitions
            ],
            "action_choice": request.action_choice,
            "response_format": request.response_format,
            "output_transport": request.output_transport,
            "extra_body": request.extra_body,
            "metadata": request.metadata,
            "max_output_repairs": request.max_output_repairs,
            "model_history": [
                item.model_dump(mode="json") for item in request.model_history
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _ModelResponseProjection(TypedDict):
    model: str
    provider_response_id: str | None
    assistant_message: ModelAssistantMessage | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


class ModelStreamProtocolFailure(BaseModel):
    """A sticky stream observation that the final SDK projection can hide."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    choice_index: int = Field(ge=0)
    reason: Literal["role_missing", "role_invalid", "role_conflict"]
    observed_role_values_json: tuple[str, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def _role_observation_shape(self) -> "ModelStreamProtocolFailure":
        expected = 0 if self.reason == "role_missing" else 1 if self.reason == "role_invalid" else 2
        if len(self.observed_role_values_json) != expected:
            raise ValueError("stream role failure requires its actual minimal observations")
        for value in self.observed_role_values_json:
            json.loads(value)
        return self


class ModelResponseRecord(BaseModel):
    """One complete, paid provider response before any typed decoding.

    The original payload is an immutable JSON string. Consumers obtain fresh
    read projections instead of mutating the persisted provider fact.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: str = Field(min_length=1)
    attempt_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    operation: str = Field(min_length=1)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_projection_ref: str = Field(min_length=1)
    provider_host: str = Field(min_length=1)
    requested_model: str = Field(min_length=1)
    model: str = Field(min_length=1)
    provider_response_id: str | None = None
    payload_json: str = Field(min_length=1)
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    stream_protocol_failures: tuple[ModelStreamProtocolFailure, ...] = ()

    @model_validator(mode="after")
    def _complete_original(self) -> "ModelResponseRecord":
        if len({item.choice_index for item in self.stream_protocol_failures}) != len(self.stream_protocol_failures):
            raise ValueError("stream protocol failures require one first failure per choice")
        projection = self._payload_projection(
            self.payload_json, self.provider_host, self.requested_model
        )
        if any(getattr(self, name) != value for name, value in projection.items()
               if name != "assistant_message"):
            raise ValueError("response projections must match the original provider payload")
        return self

    @staticmethod
    def _payload_projection(
        payload_json: str, provider_host: str, requested_model: str
    ) -> _ModelResponseProjection:
        payload = json.loads(payload_json)
        envelope = payload if isinstance(payload, dict) else {}
        usage = envelope.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        projected: _ModelResponseProjection = {
            "model": envelope.get("model") if isinstance(envelope.get("model"), str) and envelope["model"] else requested_model,
            "provider_response_id": envelope.get("id") if isinstance(envelope.get("id"), str) else None,
            "assistant_message": None,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }
        for key, aliases in (
            ("input_tokens", ("input_tokens", "prompt_tokens")),
            ("output_tokens", ("output_tokens", "completion_tokens")),
            ("total_tokens", ("total_tokens",)),
        ):
            projected[key] = next(
                (usage[name] for name in aliases
                 if isinstance(usage.get(name), int) and not isinstance(usage[name], bool) and usage[name] >= 0),
                None,
            )
        if projected["total_tokens"] is None and all(
            projected[name] is not None for name in ("input_tokens", "output_tokens")
        ):
            projected["total_tokens"] = projected["input_tokens"] + projected["output_tokens"]
        choices = envelope.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                try:
                    projected["assistant_message"] = ModelAssistantMessage(
                        provider_host=provider_host,
                        model=requested_model,
                        payload=message,
                    )
                except ValidationError:
                    pass
        return projected

    @classmethod
    def from_payload_json(
        cls,
        *,
        invocation_id: str,
        attempt_id: str,
        operation: str,
        request_digest: str,
        context_projection_ref: str,
        provider_host: str,
        requested_model: str,
        payload_json: str,
        latency_ms: float,
        stream_protocol_failures: tuple[ModelStreamProtocolFailure, ...] = (),
    ) -> "ModelResponseRecord":
        projection = cls._payload_projection(payload_json, provider_host, requested_model)
        return cls(
            invocation_id=invocation_id,
            attempt_id=attempt_id,
            operation=operation,
            request_digest=request_digest,
            context_projection_ref=context_projection_ref,
            provider_host=provider_host,
            requested_model=requested_model,
            payload_json=payload_json,
            latency_ms=latency_ms,
            model=projection["model"],
            provider_response_id=projection["provider_response_id"],
            input_tokens=projection["input_tokens"],
            output_tokens=projection["output_tokens"],
            total_tokens=projection["total_tokens"],
            stream_protocol_failures=stream_protocol_failures,
        )

    @property
    def assistant_message(self) -> ModelAssistantMessage | None:
        # Each read is a fresh typed view; callers cannot mutate the original.
        if self.stream_protocol_failures:
            return None
        return self._payload_projection(
            self.payload_json, self.provider_host, self.requested_model
        )["assistant_message"]

    @property
    def raw_response(self) -> Any:
        return json.loads(self.payload_json)


class ModelResponseSink(Protocol):
    def __call__(self, record: ModelResponseRecord) -> None: ...


class ModelInvocationContinuation(BaseModel):
    """An owner-persisted invocation identity and its ordered paid originals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_projection_ref: str = Field(min_length=1)
    response_records: tuple[ModelResponseRecord, ...] = ()

    @model_validator(mode="after")
    def _record_binding(self) -> "ModelInvocationContinuation":
        attempt_ids: set[str] = set()
        for record in self.response_records:
            if (
                record.invocation_id != self.invocation_id
                or record.operation != self.operation
                or record.request_digest != self.request_digest
                or record.context_projection_ref != self.context_projection_ref
            ):
                raise ValueError("response record does not belong to invocation")
            if record.attempt_id in attempt_ids:
                raise ValueError("invocation response attempt IDs must be unique")
            attempt_ids.add(record.attempt_id)
        return self

    @classmethod
    def for_request(
        cls,
        request: StructuredModelRequest[Any],
        *,
        invocation_id: str,
        response_records: tuple[ModelResponseRecord, ...] = (),
    ) -> "ModelInvocationContinuation":
        return cls(
            invocation_id=invocation_id,
            operation=request.operation,
            request_digest=model_request_digest(request),
            context_projection_ref=request.context_projection_ref,
            response_records=response_records,
        )

    def validate_request(self, request: StructuredModelRequest[Any]) -> None:
        if (
            self.operation != request.operation
            or self.context_projection_ref != request.context_projection_ref
            or self.request_digest != model_request_digest(request)
        ):
            raise ValueError("model invocation continuation request binding mismatch")


def sealed_context_projection_ref(
    *,
    purpose: str,
    messages: list[dict[str, Any]],
    model_history: tuple[ModelToolExchange, ...] = (),
) -> str:
    """Create a content-addressed ref for an already bounded service context.

    Agent-runtime calls should use the audited ``ContextProjection.projection_id``.
    This seal is for bounded application services whose complete input is the
    message list itself; changing any visible input creates a different ref.
    """
    canonical = json.dumps(
        {"purpose": purpose, "messages": messages,
         **({"model_history": [item.model_dump(mode="json") for item in model_history]}
            if model_history else {})},
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
    response_records: tuple[ModelResponseRecord, ...] = ()
    action_invocations: tuple[ModelActionInvocation, ...] = ()
    retry_attempts: int = 0
    retry_errors: list[str] = field(default_factory=list)
    assistant_message: ModelAssistantMessage | None = None
    protocol_exchanges: tuple[ModelToolExchange, ...] = ()

    def __post_init__(self) -> None:
        if self.value is not None and self.action_invocations:
            raise ValueError(
                "model response cannot contain both typed output and action invocations"
            )
        if self.response_records:
            first = self.response_records[0]
            ModelInvocationContinuation(
                invocation_id=first.invocation_id, operation=first.operation,
                request_digest=first.request_digest,
                context_projection_ref=first.context_projection_ref,
                response_records=self.response_records,
            )
            object.__setattr__(self, "model", self.response_records[-1].model)
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                values = [getattr(item, key) for item in self.response_records]
                known = [value for value in values if value is not None]
                total = sum(known) if known and (key == "total_tokens" or len(known) == len(values)) else None
                object.__setattr__(self, key, total)
            object.__setattr__(self, "latency_ms", round(sum(item.latency_ms for item in self.response_records), 2))

    @property
    def raw_response(self) -> Any:
        return self.response_records[-1].raw_response if self.response_records else None


class StructuredModelClient(Protocol):
    def generate(
        self,
        request: StructuredModelRequest[StructuredOutputT],
        *,
        response_sink: ModelResponseSink | None = None,
        continuation: ModelInvocationContinuation | None = None,
        before_send: Callable[[], None] | None = None,
    ) -> StructuredModelResponse[StructuredOutputT]: ...


class ModelCallIntent(BaseModel):
    call_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    purpose: str
    operation: str
    context_projection_ref: str
    sensitivity: Literal["public", "internal", "confidential", "restricted"] = (
        "internal"
    )
    structured_output_contract: str
    max_output_tokens: int | None = Field(ge=1)


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
    max_output_tokens: int | None
    policy_revision: str = "v1"


class ModelInvocationDenial(BaseModel):
    call_id: str
    reason_code: str
    message: str


__all__ = [
    "ModelAssistantMessage",
    "ModelToolResult",
    "ModelToolExchange",
    "ModelActionDefinition",
    "ModelActionInvocation",
    "ModelActionKind",
    "ModelResponseRecord",
    "ModelStreamProtocolFailure",
    "ModelResponseSink",
    "ModelInvocationContinuation",
    "model_request_digest",
    "ModelCallIntent",
    "ModelInvocationDenial",
    "ModelInvocationGrant",
    "ModelReasoningEffort",
    "ModelInvocationFailureCategory",
    "ModelInvocationUnavailable",
    "ModelCapacityCheck",
    "ModelCapacityRefused",
    "PROVIDER_DIAGNOSTIC_MAX_CHARS",
    "ProviderFailureDiagnostics",
    "ProviderExceptionFrame",
    "ModelTransportDiagnostics",
    "StructuredOutputFailure",
    "StructuredOutputFailureCode",
    "ModelRequestKind",
    "SkillActivationDecision",
    "SkillContextGrant",
    "StructuredModelClient",
    "StructuredModelRequest",
    "StructuredModelResponse",
    "StructuredOutputT",
    "sealed_context_projection_ref",
]
