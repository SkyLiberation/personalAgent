from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from personal_agent.agent.service import AgentService
from personal_agent.core.config import Settings
from personal_agent.core.models import ReviewCard
from personal_agent.review import DigestSubscription, ReviewDigestJob, ReviewFeedbackUseCase
from personal_agent.review.models import ReviewFeedbackOutcome
from personal_agent.storage.postgres_review_digest_store import PostgresReviewDigestStore
from personal_agent.web.routes._shared import is_admin, resolve_user_id


class DigestSubscriptionRequest(BaseModel):
    id: str | None = None
    user_id: str | None = None
    channel: str = "feishu"
    target_type: str = "chat_id"
    target_id: str = Field(min_length=1)
    schedule_time: str = "09:00"
    timezone: str = "Asia/Shanghai"
    enabled: bool = True


class DigestSubscriptionPatchRequest(BaseModel):
    user_id: str | None = None
    channel: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    schedule_time: str | None = None
    timezone: str | None = None
    enabled: bool | None = None


class DigestSubscriptionListResponse(BaseModel):
    items: list[dict[str, object]] = Field(default_factory=list)


class DigestDeliveryListResponse(BaseModel):
    items: list[dict[str, object]] = Field(default_factory=list)


class ReviewCardListResponse(BaseModel):
    items: list[ReviewCard] = Field(default_factory=list)


class ReviewFeedbackRequest(BaseModel):
    user_id: str | None = None
    outcome: ReviewFeedbackOutcome


def register_review_routes(
    app: FastAPI,
    *,
    settings: Settings,
    service: AgentService,
    review_digest_store: PostgresReviewDigestStore,
    review_feedback_use_case: ReviewFeedbackUseCase,
) -> None:
    @app.get("/api/review/digest/subscriptions", response_model=DigestSubscriptionListResponse)
    def list_digest_subscriptions(
        request: Request,
        enabled_only: bool = False,
    ) -> DigestSubscriptionListResponse:
        caller = resolve_user_id(request, settings)
        subscriptions = review_digest_store.list_subscriptions(enabled_only=enabled_only)
        if not is_admin(request):
            subscriptions = [item for item in subscriptions if item.user_id == caller]
        return DigestSubscriptionListResponse(
            items=[item.model_dump(mode="json") for item in subscriptions]
        )

    @app.post("/api/review/digest/subscriptions")
    def create_digest_subscription(
        body: DigestSubscriptionRequest,
        request: Request,
    ) -> dict[str, object]:
        caller = resolve_user_id(request, settings)
        user_id = body.user_id if is_admin(request) and body.user_id else caller
        subscription = DigestSubscription(
            id=body.id or uuid4().hex,
            user_id=user_id,
            channel=body.channel,
            target_type=body.target_type,
            target_id=body.target_id,
            schedule_time=body.schedule_time,
            timezone=body.timezone,
            enabled=body.enabled,
        )
        saved = review_digest_store.upsert_subscription(subscription)
        return saved.model_dump(mode="json")

    @app.patch("/api/review/digest/subscriptions/{subscription_id}")
    def update_digest_subscription(
        subscription_id: str,
        body: DigestSubscriptionPatchRequest,
        request: Request,
    ) -> dict[str, object]:
        existing = _get_digest_subscription_or_404(
            review_digest_store,
            subscription_id,
            request,
            settings,
        )
        updates = {
            key: value
            for key, value in body.model_dump().items()
            if value is not None
        }
        if not is_admin(request):
            updates.pop("user_id", None)
        saved = review_digest_store.upsert_subscription(existing.model_copy(update=updates))
        return saved.model_dump(mode="json")

    @app.post("/api/review/digest/subscriptions/{subscription_id}/send-now")
    def send_digest_now(
        subscription_id: str,
        request: Request,
    ) -> dict[str, object]:
        subscription = _get_digest_subscription_or_404(
            review_digest_store,
            subscription_id,
            request,
            settings,
        )
        job = ReviewDigestJob(
            service.review_digest_use_case,
            app.state.review_digest_delivery_router,
            ledger=review_digest_store,
        )
        result = job.run(subscription)
        return result.model_dump(mode="json")

    @app.get("/api/review/digest/deliveries", response_model=DigestDeliveryListResponse)
    def list_digest_deliveries(
        request: Request,
        subscription_id: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
    ) -> DigestDeliveryListResponse:
        resolved_user = user_id if is_admin(request) else resolve_user_id(request, settings)
        items = review_digest_store.list_deliveries(
            subscription_id=subscription_id,
            user_id=resolved_user,
            limit=limit,
        )
        return DigestDeliveryListResponse(items=[_jsonable_row(item) for item in items])

    @app.get("/api/review/cards", response_model=ReviewCardListResponse)
    def list_review_cards(
        request: Request,
        user_id: str | None = None,
        due_only: bool = False,
    ) -> ReviewCardListResponse:
        resolved_user = user_id if is_admin(request) and user_id else resolve_user_id(request, settings)
        cards = (
            service.memory.due_reviews(resolved_user)
            if due_only else service.memory.list_reviews(resolved_user)
        )
        return ReviewCardListResponse(items=cards)

    @app.post("/api/review/cards/{review_card_id}/feedback")
    def submit_review_card_feedback(
        review_card_id: str,
        body: ReviewFeedbackRequest,
        request: Request,
    ) -> dict[str, object]:
        resolved_user = body.user_id if is_admin(request) and body.user_id else resolve_user_id(request, settings)
        result = review_feedback_use_case.apply_to_review_card(
            user_id=resolved_user,
            review_card_id=review_card_id,
            outcome=body.outcome,
            source_channel="web",
        )
        if not result.ok:
            raise HTTPException(status_code=404, detail=result.error or "Review card not found.")
        return result.model_dump(mode="json")


def _get_digest_subscription_or_404(
    store: PostgresReviewDigestStore,
    subscription_id: str,
    request: Request,
    settings: Settings,
) -> DigestSubscription:
    subscription = store.get_subscription(subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Digest subscription not found.")
    caller = resolve_user_id(request, settings)
    if not is_admin(request) and subscription.user_id != caller:
        raise HTTPException(status_code=404, detail="Digest subscription not found.")
    return subscription


def _jsonable_row(row: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result
