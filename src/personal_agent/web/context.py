from __future__ import annotations

from dataclasses import dataclass
from logging import Logger

from fastapi import FastAPI

from ..agent.service import AgentService
from ..capture import CaptureService
from ..core.config import Settings
from ..feishu import FeishuService
from ..insight import (
    KnowledgeGapJob,
    KnowledgeGapJobRunner,
    KnowledgeGapScheduler,
)
from ..review import (
    ReviewDigestJob,
    ReviewDigestJobRunner,
    ReviewDigestScheduler,
    ReviewFeedbackUseCase,
    subscriptions_from_settings,
)
from ..review.delivery import DeliveryRouter, FeishuDeliveryProvider
from ..research import ResearchScheduler, ResearchSchedulerRunner
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
    knowledge_gap_runner: KnowledgeGapJobRunner
    research_runner: ResearchSchedulerRunner

    def attach_to(self, app: FastAPI) -> None:
        app.state.context = self
        app.state.service = self.service
        app.state.review_digest_store = self.review_digest_store
        app.state.review_digest_delivery_router = self.review_digest_delivery_router
        app.state.review_digest_runner = self.review_digest_runner
        app.state.research_runner = self.research_runner

    def startup(self) -> None:
        for subscription in subscriptions_from_settings(self.settings):
            self.review_digest_store.upsert_subscription(subscription)
        self.feishu_service.start_event_listener()
        if self.settings.review_digest.scheduler_enabled:
            self.review_digest_runner.start()
        if self.settings.knowledge_gap.scheduler_enabled:
            self.knowledge_gap_runner.start()
        if self.settings.research.scheduler_enabled:
            self.research_runner.start()

    def shutdown(self) -> None:
        self.review_digest_runner.stop()
        self.knowledge_gap_runner.stop()
        self.research_runner.stop()


class _GapSubscriptionStore:
    """Adapt digest subscriptions to the knowledge-gap schedule.

    The gap job targets the same chat ids as the review digest, but fires on its
    own ``schedule_time`` so the two never collide. This wraps the digest store
    and rewrites only the schedule.
    """

    def __init__(self, digest_store: PostgresReviewDigestStore, schedule_time: str) -> None:
        self._store = digest_store
        self._schedule_time = schedule_time

    def list_subscriptions(self, *, enabled_only: bool = True):
        return [
            subscription.model_copy(update={"schedule_time": self._schedule_time})
            for subscription in self._store.list_subscriptions(enabled_only=enabled_only)
        ]


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
    service.research_service.set_delivery_router(review_digest_delivery_router)
    review_digest_job = ReviewDigestJob(
        service.review_digest_use_case,
        review_digest_delivery_router,
        ledger=review_digest_store,
    )
    review_digest_runner = ReviewDigestJobRunner(
        ReviewDigestScheduler(review_digest_store, review_digest_job),
        tick_seconds=settings.review_digest.scheduler_tick_seconds,
    )
    knowledge_gap_job = KnowledgeGapJob(
        service.knowledge_gap_use_case,
        review_digest_delivery_router,
        ledger=review_digest_store,
    )
    knowledge_gap_runner = KnowledgeGapJobRunner(
        KnowledgeGapScheduler(
            _GapSubscriptionStore(review_digest_store, settings.knowledge_gap.schedule_time),
            knowledge_gap_job,
        ),
        tick_seconds=settings.knowledge_gap.scheduler_tick_seconds,
    )
    research_runner = ResearchSchedulerRunner(
        ResearchScheduler(service.research_store, service.research_service),
        tick_seconds=settings.research.scheduler_tick_seconds,
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
        knowledge_gap_runner=knowledge_gap_runner,
        research_runner=research_runner,
    )
