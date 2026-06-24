from __future__ import annotations

import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable

from personal_agent.core.logging_utils import log_event

logger = logging.getLogger(__name__)

# Optional durable sink for policy decisions. Registered by the runtime so both
# the tool gateway and the memory facade persist authorization outcomes without
# changing their call sites. Failures here must never break the request path.
_policy_decision_sink: Callable[[dict[str, Any]], None] | None = None


def set_policy_decision_sink(sink: Callable[[dict[str, Any]], None] | None) -> None:
    """Register (or clear) the durable sink for policy decisions."""
    global _policy_decision_sink
    _policy_decision_sink = sink


def record_metric(
    name: str,
    *,
    value: float = 1.0,
    unit: str = "count",
    dimensions: dict[str, object] | None = None,
) -> None:
    """Emit a structured metric event for log-based aggregation."""
    log_event(
        logger,
        logging.INFO,
        "metric",
        metric_name=name,
        metric_value=value,
        metric_unit=unit,
        **(dimensions or {}),
    )


def _current_langsmith_run_id() -> str | None:
    """Return the active LangSmith run id, if a trace is in progress."""
    try:
        from langsmith.run_helpers import get_current_run_tree

        run_tree = get_current_run_tree()
        if run_tree is not None and run_tree.id is not None:
            return str(run_tree.id)
    except Exception:  # pragma: no cover - tracing must never break audit
        pass
    return None


def _event_payload(event: Any) -> dict[str, Any]:
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json")
    return dict(event)


def record_tool_audit(event: Any) -> None:
    """Emit the normalized business audit event for a tool invocation."""
    payload = _event_payload(event)
    if not payload.get("audit_required", True):
        return
    log_event(
        logger,
        logging.INFO if payload.get("artifact_ok") else logging.WARNING,
        "tool.audit",
        **payload,
    )
    record_metric(
        "tool.invocation",
        dimensions={
            "tool_name": payload.get("tool_name"),
            "execution_mode": payload.get("execution_mode"),
            "risk_level": payload.get("risk_level"),
            "ok": payload.get("artifact_ok"),
        },
    )


def record_policy_decision(
    *,
    action: str,
    effect: str,
    rule: str,
    reason: str = "",
    tool_name: str | None = None,
    permission_scope: str | None = None,
    resource: str | None = None,
    risk_level: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    source_platform: str | None = None,
    execution_mode: str | None = None,
    thread_id: str | None = None,
    run_id: str | None = None,
    audit_required: bool = True,
) -> None:
    """Record why the policy engine allowed / denied / required confirmation.

    Non-allow decisions are always logged so authorization outcomes stay
    queryable. Plain allows respect ``audit_required`` to avoid log noise.
    """
    if effect == "allow" and not audit_required:
        return
    payload = {
        "action": action,
        "effect": effect,
        "rule": rule,
        "reason": reason,
        "tool_name": tool_name,
        "permission_scope": permission_scope,
        "resource": resource,
        "risk_level": risk_level,
        "user_id": user_id,
        "session_id": session_id,
        "source_platform": source_platform,
        "execution_mode": execution_mode,
        "thread_id": thread_id,
        "run_id": run_id,
        "langsmith_run_id": _current_langsmith_run_id(),
    }
    log_event(
        logger,
        logging.INFO if effect == "allow" else logging.WARNING,
        "policy.decision",
        **payload,
    )
    if _policy_decision_sink is not None:
        try:
            _policy_decision_sink(payload)
        except Exception:  # pragma: no cover - persistence must never break the request
            logger.exception("Failed to persist policy decision")
    record_metric(
        "policy.decision",
        dimensions={
            "action": action,
            "effect": effect,
            "rule": rule,
            "tool_name": tool_name,
            "risk_level": risk_level,
        },
    )


def record_verification_result(
    *,
    question: str,
    answer: str,
    result: Any,
    matches_count: int,
    citations_count: int,
    web_enabled: bool,
    evidence_count: int,
    latency_ms: float,
    run_id: str | None = None,
    thread_id: str | None = None,
    user_id: str | None = None,
    step_id: str | None = None,
) -> None:
    """Record verifier observability without uploading raw answer text."""
    issues = list(getattr(result, "issues", []) or [])
    warnings = list(getattr(result, "warnings", []) or [])
    claim_checks = list(getattr(result, "claim_checks", []) or [])
    statuses: dict[str, int] = {}
    for check in claim_checks:
        status = str(getattr(check, "status", "unknown"))
        statuses[status] = statuses.get(status, 0) + 1

    payload = {
        "prompt_name": "verifier",
        "prompt_version": "rules-v1",
        "parse_schema": "VerificationResult",
        "parse_ok": True,
        "run_id": run_id,
        "thread_id": thread_id,
        "user_id": user_id,
        "step_id": step_id,
        "question_chars": len(question or ""),
        "answer_chars": len(answer or ""),
        "matches_count": matches_count,
        "citations_count": citations_count,
        "web_enabled": web_enabled,
        "evidence_count": evidence_count,
        "evidence_score": getattr(result, "evidence_score", None),
        "citation_valid": getattr(result, "citation_valid", None),
        "ok": getattr(result, "ok", None),
        "sufficient": getattr(result, "sufficient", None),
        "issue_count": len(issues),
        "warning_count": len(warnings),
        "claim_check_count": len(claim_checks),
        "claim_statuses": statuses or None,
        "latency_ms": latency_ms,
    }
    log_event(
        logger,
        logging.INFO if getattr(result, "ok", False) else logging.WARNING,
        "verifier.result",
        **payload,
    )
    record_metric(
        "verifier.run",
        dimensions={
            "ok": getattr(result, "ok", None),
            "sufficient": getattr(result, "sufficient", None),
            "citation_valid": getattr(result, "citation_valid", None),
        },
    )


@dataclass(slots=True)
class RunMetrics:
    run_id: str
    thread_id: str = ""
    user_id: str = ""
    session_id: str = ""
    intent: str = "unknown"
    started_at: float = field(default_factory=perf_counter)

    def complete(self, *, status: str, **dimensions: object) -> None:
        duration_ms = round((perf_counter() - self.started_at) * 1000, 2)
        record_metric(
            "agent.run",
            value=duration_ms,
            unit="ms",
            dimensions={
                "run_id": self.run_id,
                "thread_id": self.thread_id,
                "user_id": self.user_id,
                "session_id": self.session_id,
                "intent": self.intent,
                "status": status,
                **dimensions,
            },
        )
