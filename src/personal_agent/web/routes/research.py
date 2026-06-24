from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from ...agent.service import AgentService
from ...core.config import Settings
from ...research import (
    ContentPreferences,
    DeliveryTarget,
    ResearchFeedback,
    ResearchSubscription,
    SchedulePolicy,
    SourcePreferences,
)
from ._shared import is_admin, resolve_user_id


class ResearchSubscriptionRequest(BaseModel):
    user_id: str | None = None
    name: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    instructions: str = ""
    seed_queries: list[str] = Field(default_factory=list)
    lookback_hours: int = Field(default=24, ge=1, le=720)
    max_items: int = Field(default=5, ge=1, le=20)
    schedule: SchedulePolicy = Field(default_factory=SchedulePolicy)
    delivery: DeliveryTarget = Field(default_factory=DeliveryTarget)
    source_preferences: SourcePreferences = Field(default_factory=SourcePreferences)
    content_preferences: ContentPreferences = Field(default_factory=ContentPreferences)
    enabled: bool = True


class ResearchSubscriptionPatch(BaseModel):
    name: str | None = None
    topic: str | None = None
    instructions: str | None = None
    seed_queries: list[str] | None = None
    lookback_hours: int | None = Field(default=None, ge=1, le=720)
    max_items: int | None = Field(default=None, ge=1, le=20)
    schedule: SchedulePolicy | None = None
    delivery: DeliveryTarget | None = None
    source_preferences: SourcePreferences | None = None
    content_preferences: ContentPreferences | None = None
    enabled: bool | None = None


class ResearchOnceRequest(BaseModel):
    user_id: str | None = None
    topic: str = Field(min_length=1)
    instructions: str = ""
    max_items: int = Field(default=5, ge=1, le=20)
    lookback_hours: int = Field(default=24, ge=1, le=720)


class ResearchFeedbackRequest(BaseModel):
    action: str
    run_id: str
    event_id: str | None = None
    subscription_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


def register_research_routes(
    app: FastAPI, *, settings: Settings, service: AgentService
) -> None:
    store = service.research_store

    @app.get("/api/research/subscriptions")
    def list_subscriptions(request: Request, enabled_only: bool = False):
        user_id = resolve_user_id(request, settings)
        items = store.list_subscriptions(
            user_id=None if is_admin(request) else user_id,
            enabled_only=enabled_only,
        )
        return {"items": [item.model_dump(mode="json") for item in items]}

    @app.post("/api/research/subscriptions")
    def create_subscription(body: ResearchSubscriptionRequest, request: Request):
        caller = resolve_user_id(request, settings)
        user_id = body.user_id if is_admin(request) and body.user_id else caller
        saved = service.create_research_subscription(ResearchSubscription(
            user_id=user_id,
            **body.model_dump(exclude={"user_id"}),
        ))
        return saved.model_dump(mode="json")

    @app.patch("/api/research/subscriptions/{subscription_id}")
    def update_subscription(
        subscription_id: str, body: ResearchSubscriptionPatch, request: Request
    ):
        existing = _subscription_or_404(service, subscription_id, request, settings)
        updates = {key: value for key, value in body.model_dump().items() if value is not None}
        saved = service.research_service.update_subscription(
            existing.model_copy(update=updates)
        )
        return saved.model_dump(mode="json")

    @app.delete("/api/research/subscriptions/{subscription_id}")
    def delete_subscription(subscription_id: str, request: Request):
        existing = _subscription_or_404(service, subscription_id, request, settings)
        return {"ok": store.delete_subscription(existing.id, user_id=existing.user_id)}

    @app.post("/api/research/subscriptions/{subscription_id}/run-now")
    def run_subscription_now(subscription_id: str, request: Request):
        _subscription_or_404(service, subscription_id, request, settings)
        run = service.enqueue_research_subscription(subscription_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Research subscription not found.")
        return run.model_dump(mode="json")

    @app.post("/api/research/once")
    def run_once(body: ResearchOnceRequest, request: Request):
        caller = resolve_user_id(request, settings)
        user_id = body.user_id if is_admin(request) and body.user_id else caller
        run = service.run_research_once(
            user_id=user_id,
            topic=body.topic,
            instructions=body.instructions,
            max_items=body.max_items,
            lookback_hours=body.lookback_hours,
        )
        return run.model_dump(mode="json")

    @app.get("/api/research/runs")
    def list_runs(request: Request, limit: int = 50):
        user_id = resolve_user_id(request, settings)
        return {
            "items": [
                item.model_dump(mode="json")
                for item in store.list_runs(user_id=user_id, limit=limit)
            ]
        }

    @app.get("/api/research/runs/{run_id}")
    def get_run(run_id: str, request: Request):
        run = store.get_run(run_id)
        _check_user(run.user_id if run else None, request, settings)
        if run is None:
            raise HTTPException(status_code=404, detail="Research run not found.")
        digest = store.get_digest(run.digest_id) if run.digest_id else None
        return {
            "run": run.model_dump(mode="json"),
            "digest": digest.model_dump(mode="json") if digest else None,
        }

    @app.post("/api/research/feedback")
    def submit_feedback(body: ResearchFeedbackRequest, request: Request):
        run = store.get_run(body.run_id)
        _check_user(run.user_id if run else None, request, settings)
        if run is None:
            raise HTTPException(status_code=404, detail="Research run not found.")
        try:
            feedback = ResearchFeedback(
                user_id=run.user_id,
                run_id=run.id,
                event_id=body.event_id,
                subscription_id=body.subscription_id or run.subscription_id,
                action=body.action,
                source_channel="web",
                payload=body.payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return service.submit_research_feedback(feedback).model_dump(mode="json")

    @app.post("/api/research/events/{event_id}/save")
    def save_event(event_id: str, request: Request):
        user_id = resolve_user_id(request, settings)
        result = service.save_research_event(event_id, user_id=user_id)
        note = getattr(result, "note", None)
        return {"ok": True, "note_id": getattr(note, "id", None)}


def _subscription_or_404(
    service: AgentService,
    subscription_id: str,
    request: Request,
    settings: Settings,
) -> ResearchSubscription:
    item = service.research_store.get_subscription(subscription_id)
    _check_user(item.user_id if item else None, request, settings)
    if item is None:
        raise HTTPException(status_code=404, detail="Research subscription not found.")
    return item


def _check_user(
    owner: str | None, request: Request, settings: Settings
) -> None:
    if owner is None:
        return
    if not is_admin(request) and owner != resolve_user_id(request, settings):
        raise HTTPException(status_code=404, detail="Resource not found.")

