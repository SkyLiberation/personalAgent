"""Deterministic normalization of executor failures for executive policy."""

from __future__ import annotations

from dataclasses import dataclass

from personal_agent.kernel.contracts.executive import ObservationRef, RetryDirective


@dataclass(frozen=True, slots=True)
class FailureClassification:
    error_code: str
    retryable: bool


def classify_failure(reason: str) -> FailureClassification:
    lowered = reason.lower()
    if any(token in lowered for token in (
        "timeout", "timed out", "rate limit", "temporar", "connection", "network",
        "unavailable", "429", "502", "503", "504",
    )):
        return FailureClassification("transient_provider_failure", True)
    if any(token in lowered for token in (
        "unauthorized", "forbidden", "permission", "credential", "authentication", "401", "403",
    )):
        return FailureClassification("authorization_required", False)
    if any(token in lowered for token in (
        "invalid", "schema", "validation", "malformed", "unsupported", "not found", "404",
    )):
        return FailureClassification("invalid_or_unsupported_request", False)
    if "budget" in lowered or "limit is exhausted" in lowered:
        return FailureClassification("budget_exhausted", False)
    return FailureClassification("executor_failure", False)


class ObservationNormalizer:
    def normalize(
        self,
        *,
        goal_id: str,
        provenance: str,
        summary: str,
        payload: dict[str, object] | None = None,
    ) -> ObservationRef:
        classification = classify_failure(summary)
        normalized_payload = dict(payload or {})
        normalized_payload.update({
            "error_code": classification.error_code,
            "retryable": classification.retryable,
        })
        return ObservationRef(
            goal_id=goal_id,
            kind="action_failure",
            provenance=provenance,
            summary=summary,
            payload=normalized_payload,
        )


class TechnicalRecoveryPolicy:
    """Authorize bounded technical retries without selecting a provider."""

    def directive(
        self,
        observation: ObservationRef,
        *,
        requirement_id: str,
        idempotency_key: str,
        attempt_count: int,
        max_attempts: int,
        action_idempotent: bool,
        failed_provider_id: str = "",
    ) -> RetryDirective:
        retryable = bool(observation.payload.get("retryable"))
        allowed = retryable and action_idempotent and attempt_count < max_attempts
        return RetryDirective(
            requirement_id=requirement_id,
            retry_kind="equivalent_provider" if allowed and failed_provider_id else (
                "same_provider" if allowed else "none"
            ),
            excluded_provider_ids=(failed_provider_id,) if allowed and failed_provider_id else (),
            preserve_contract=True,
            idempotency_key=idempotency_key,
        )


__all__ = [
    "FailureClassification",
    "ObservationNormalizer",
    "TechnicalRecoveryPolicy",
    "classify_failure",
]
