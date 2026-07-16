"""Single admission and grant boundary for every model invocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Iterator

from personal_agent.capabilities.contracts.model import (
    ModelCallIntent,
    ModelInvocationDenial,
    ModelInvocationGrant,
    SkillActivationDecision,
    SkillContextGrant,
    StructuredModelClient,
    StructuredModelRequest,
    StructuredModelResponse,
    StructuredOutputT,
    StreamingModelClient,
    StreamChunk,
)


class ModelInvocationDenied(PermissionError):
    def __init__(self, denial: ModelInvocationDenial) -> None:
        super().__init__(denial.message)
        self.denial = denial


@dataclass(frozen=True, slots=True)
class ModelInvocationAudit:
    intent: ModelCallIntent
    skill_decision: SkillActivationDecision
    skill_context_grant: SkillContextGrant
    invocation_grant: ModelInvocationGrant


class ModelInvocationAdmission:
    def __init__(self, *, max_output_tokens: int = 32_768) -> None:
        self.max_output_tokens = max_output_tokens

    def grant(
        self,
        intent: ModelCallIntent,
        *,
        provider: str,
        model: str,
    ) -> ModelInvocationGrant:
        if not intent.context_projection_ref:
            raise ModelInvocationDenied(ModelInvocationDenial(
                call_id=intent.call_id,
                reason_code="context_projection_missing",
                message="model invocation requires a context projection reference",
            ))
        if intent.max_output_tokens > self.max_output_tokens:
            raise ModelInvocationDenied(ModelInvocationDenial(
                call_id=intent.call_id,
                reason_code="output_budget_exceeded",
                message="model invocation exceeds the configured output budget",
            ))
        if intent.sensitivity == "restricted" and provider != "local":
            raise ModelInvocationDenied(ModelInvocationDenial(
                call_id=intent.call_id,
                reason_code="restricted_egress_denied",
                message="restricted context cannot be sent to an external model provider",
            ))
        return ModelInvocationGrant(
            call_id=intent.call_id,
            purpose=intent.purpose,
            provider=provider,
            model=model,
            allowed_egress="sensitive" if intent.sensitivity == "confidential" else "content",
            context_projection_ref=intent.context_projection_ref,
            max_input_tokens=intent.max_input_tokens,
            max_output_tokens=intent.max_output_tokens,
        )


class GovernedModelClient(Generic[StructuredOutputT]):
    """Protocol façade: creates a one-call grant before touching the provider."""

    def __init__(
        self,
        delegate: StructuredModelClient,
        *,
        provider: str,
        model: str,
        admission: ModelInvocationAdmission | None = None,
    ) -> None:
        self._delegate = delegate
        self.provider = provider
        self.model = model
        self._admission = admission or ModelInvocationAdmission()
        self.last_audit: ModelInvocationAudit | None = None

    @property
    def transport(self) -> StructuredModelClient:
        """Return the admitted provider transport for composition diagnostics."""
        return self._delegate

    def generate(
        self,
        request: StructuredModelRequest[StructuredOutputT],
    ) -> StructuredModelResponse[StructuredOutputT]:
        projection_ref = str(request.context_projection_ref or "")
        intent = ModelCallIntent(
            purpose=request.operation,
            operation=request.operation,
            context_projection_ref=projection_ref,
            sensitivity=request.sensitivity,
            structured_output_contract=request.output_type.__name__,
            max_input_tokens=max(1, int(request.metadata.get("max_input_tokens", 128_000))),
            max_output_tokens=request.max_tokens,
        )
        skill_decision = SkillActivationDecision(
            call_id=intent.call_id,
            reason_codes=("no_contextual_skill_required",),
        )
        skill_grant = SkillContextGrant(call_id=intent.call_id)
        grant = self._admission.grant(intent, provider=self.provider, model=self.model)
        self.last_audit = ModelInvocationAudit(intent, skill_decision, skill_grant, grant)
        response = self._delegate.generate(request)
        if grant.call_id != intent.call_id or grant.purpose != request.operation:
            raise RuntimeError("model invocation grant scope mismatch")
        return response


class GovernedStreamingModelClient:
    """Streaming façade with the same one-call admission as structured calls."""

    def __init__(
        self,
        delegate: StreamingModelClient,
        *,
        provider: str,
        model: str,
        admission: ModelInvocationAdmission | None = None,
    ) -> None:
        self._delegate = delegate
        self.provider = provider
        self.model = model
        self._admission = admission or ModelInvocationAdmission()
        self.last_audit: ModelInvocationAudit | None = None

    @property
    def transport(self) -> StreamingModelClient:
        return self._delegate

    def stream(self, request: StructuredModelRequest[Any]) -> Iterator[StreamChunk]:
        intent = ModelCallIntent(
            purpose=request.operation,
            operation=request.operation,
            context_projection_ref=str(request.context_projection_ref or ""),
            sensitivity=request.sensitivity,
            structured_output_contract=request.output_type.__name__,
            max_input_tokens=max(1, int(request.metadata.get("max_input_tokens", 128_000))),
            max_output_tokens=request.max_tokens,
        )
        skill_decision = SkillActivationDecision(
            call_id=intent.call_id,
            reason_codes=("no_contextual_skill_required",),
        )
        skill_grant = SkillContextGrant(call_id=intent.call_id)
        grant = self._admission.grant(intent, provider=self.provider, model=self.model)
        self.last_audit = ModelInvocationAudit(intent, skill_decision, skill_grant, grant)
        yield from self._delegate.stream(request)


__all__ = [
    "GovernedModelClient", "GovernedStreamingModelClient", "ModelInvocationAdmission", "ModelInvocationAudit",
    "ModelInvocationDenied",
]
