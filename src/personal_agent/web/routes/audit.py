from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI, HTTPException, Request

from ...agent.service import AgentService
from ...core.config import Settings
from ._shared import is_admin, resolve_user_id


def register_audit_routes(
    app: FastAPI,
    *,
    settings: Settings,
    service: AgentService,
) -> None:
    @app.get("/api/audit/events")
    def query_audit_events(
        request: Request,
        user_id: str | None = None,
        tool_name: str | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
        risk_level: str | None = None,
        execution_mode: str | None = None,
        side_effect_id: str | None = None,
        artifact_ok: bool | None = None,
        since: str | None = None,
        until: str | None = None,
        reveal: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        admin = is_admin(request)
        caller = resolve_user_id(request, settings)
        resolved_user = user_id if admin else caller
        allow_reveal = reveal and admin
        events = service.query_tool_audit(
            user_id=resolved_user,
            tool_name=tool_name,
            thread_id=thread_id,
            run_id=run_id,
            risk_level=risk_level,
            execution_mode=execution_mode,
            side_effect_id=side_effect_id,
            artifact_ok=artifact_ok,
            since=_parse_iso(since),
            until=_parse_iso(until),
            reveal=allow_reveal,
            limit=limit,
            offset=offset,
        )
        return {"items": events, "redacted": not allow_reveal}

    @app.get("/api/audit/events/by-idempotency/{idempotency_key}")
    def trace_tool_call(
        idempotency_key: str, request: Request, reveal: bool = False,
    ) -> dict[str, object]:
        if not is_admin(request):
            raise HTTPException(status_code=403, detail="需要管理员权限。")
        trace = service.trace_tool_call(idempotency_key, reveal=reveal)
        if trace is None:
            raise HTTPException(status_code=404, detail="未找到该 idempotency_key 的调用记录。")
        return trace

    @app.get("/api/audit/policy-decisions")
    def query_policy_decisions(
        request: Request,
        user_id: str | None = None,
        tool_name: str | None = None,
        effect: str | None = None,
        action: str | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        if not is_admin(request):
            raise HTTPException(status_code=403, detail="需要管理员权限。")
        items = service.query_policy_decisions(
            user_id=user_id,
            tool_name=tool_name,
            effect=effect,
            action=action,
            thread_id=thread_id,
            run_id=run_id,
            since=_parse_iso(since),
            until=_parse_iso(until),
            limit=limit,
            offset=offset,
        )
        return {"items": items}

    @app.get("/api/audit/metrics")
    def audit_metrics(request: Request, window_hours: int = 24) -> dict[str, object]:
        if not is_admin(request):
            raise HTTPException(status_code=403, detail="需要管理员权限。")
        metrics = service.audit_metrics(window_hours=window_hours)
        alerts = _audit_alerts(metrics)
        if alerts:
            from ...core.observability import record_metric
            for alert in alerts:
                record_metric("audit.alert", dimensions={"kind": alert["kind"]})
        return {"metrics": metrics, "alerts": alerts}


def _parse_iso(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的时间格式：{value}（应为 ISO-8601）。")


_AUDIT_ALERT_THRESHOLDS: dict[str, float] = {
    "delete_failure_rate": 0.2,
    "failure_rate": 0.3,
    "duplicate_side_effects": 3,
    "policy_denials": 10,
}


def _audit_alerts(metrics: dict[str, object]) -> list[dict[str, object]]:
    alerts: list[dict[str, object]] = []
    for kind, threshold in _AUDIT_ALERT_THRESHOLDS.items():
        value = metrics.get(kind)
        if isinstance(value, (int, float)) and value > threshold:
            alerts.append({"kind": kind, "value": value, "threshold": threshold})
    return alerts
