from __future__ import annotations

from dataclasses import dataclass
from logging import Logger

from fastapi import FastAPI

from ..agent.service import AgentService
from ..capture import CaptureService
from ..core.config import Settings
from ..feishu import FeishuService
from ..review import (
    ReviewDigestJob,
    ReviewDigestJobRunner,
    ReviewDigestScheduler,
    ReviewDigestUseCase,
    ReviewFeedbackUseCase,
    subscriptions_from_settings,
)
from ..review.delivery import DeliveryRouter, FeishuDeliveryProvider
from ..storage.postgres_review_digest_store import PostgresReviewDigestStore


@dataclass(slots=True)
class WebAppContext:
    settings: Settings
    capture_service: CaptureService
    service: AgentService
    feishu_service: FeishuService
    review_digest_store: PostgresReviewDigestStore
    review_digest_delivery_router: DeliveryRouter
    review_digest_runner: ReviewDigestJobRunner
    review_feedback_use_case: ReviewFeedbackUseCase

    def attach_to(self, app: FastAPI) -> None:
        app.state.context = self
        app.state.service = self.service
        app.state.review_digest_store = self.review_digest_store
        app.state.review_digest_delivery_router = self.review_digest_delivery_router
        app.state.review_digest_runner = self.review_digest_runner

    def startup(self) -> None:
        for subscription in subscriptions_from_settings(self.settings):
            self.review_digest_store.upsert_subscription(subscription)
        self.feishu_service.start_event_listener()
        if self.settings.review_digest.scheduler_enabled:
            self.review_digest_runner.start()

    def shutdown(self) -> None:
        self.review_digest_runner.stop()


def build_web_app_context(settings: Settings, logger: Logger) -> WebAppContext:
    capture_service = CaptureService(settings, logger)
    service = AgentService(settings, capture_service=capture_service)
    review_digest_store = PostgresReviewDigestStore(settings.postgres_url or "")
    review_feedback_use_case = ReviewFeedbackUseCase(service.memory, review_digest_store)
    feishu_service = FeishuService(
        settings,
        service,
        review_feedback_use_case=review_feedback_use_case,
        review_digest_store=review_digest_store,
    )
    review_digest_delivery_router = DeliveryRouter({"feishu": FeishuDeliveryProvider(feishu_service)})
    review_digest_job = ReviewDigestJob(
        ReviewDigestUseCase(service.memory),
        review_digest_delivery_router,
        ledger=review_digest_store,
    )
    review_digest_runner = ReviewDigestJobRunner(
        ReviewDigestScheduler(review_digest_store, review_digest_job),
        tick_seconds=settings.review_digest.scheduler_tick_seconds,
    )
    return WebAppContext(
        settings=settings,
        capture_service=capture_service,
        service=service,
        feishu_service=feishu_service,
        review_digest_store=review_digest_store,
        review_digest_delivery_router=review_digest_delivery_router,
        review_digest_runner=review_digest_runner,
        review_feedback_use_case=review_feedback_use_case,
    )
