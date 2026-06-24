"""Background job that detects knowledge gaps and asks the user about them.

Mirrors the review-digest job/scheduler/runner trio so it reuses the same
delivery channel and in-process scheduling, but instead of pushing review cards
it pushes a single proactive question derived from :class:`KnowledgeGapAnalyzer`.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from personal_agent.kernel.models import local_now
from personal_agent.review.models import DeliveryMessage, DeliveryTarget, DigestSubscription
from personal_agent.review.scheduler import is_subscription_due
from personal_agent.insight.service import KnowledgeGapUseCase

logger = logging.getLogger(__name__)


class KnowledgeGapDeliveryProvider(Protocol):
    def send(self, target: DeliveryTarget, message: DeliveryMessage):  # -> DeliveryResult
        ...


class KnowledgeGapSubscriptionStore(Protocol):
    def list_subscriptions(self, *, enabled_only: bool = True) -> list[DigestSubscription]:
        ...


class KnowledgeGapLedger(Protocol):
    def claim_gap_delivery(self, subscription_id: str, gap_date: str) -> bool:
        """Return True if this caller won the per-(subscription, day) claim."""
        ...


class KnowledgeGapJobResult(BaseModel):
    subscription_id: str
    user_id: str
    channel: str
    target_id: str
    delivered: bool
    gaps_found: int = 0
    skipped: bool = False
    error: str | None = None


class KnowledgeGapJob:
    """Detect gaps for a subscription and deliver one question if any exist."""

    def __init__(
        self,
        use_case: KnowledgeGapUseCase,
        delivery_router: KnowledgeGapDeliveryProvider,
        ledger: KnowledgeGapLedger | None = None,
    ) -> None:
        self.use_case = use_case
        self.delivery_router = delivery_router
        # Durable per-(subscription, day) claim store. When absent, fall back to
        # an in-process guard — both stop the scheduler's tick loop from
        # re-delivering after schedule_time (which keeps is_subscription_due
        # True for the rest of the day, so a 300s tick would otherwise spam the
        # user every 5 minutes until midnight). The ledger additionally survives
        # process restarts.
        self.ledger = ledger
        self._delivered_on: dict[str, str] = {}

    def _already_delivered_today(self, subscription_id: str, today: str) -> bool:
        if self.ledger is None:
            return self._delivered_on.get(subscription_id) == today
        # claim_gap_delivery is atomic: winning the claim means "deliver now".
        # Losing it means another run (or a prior process) already claimed today.
        return not self.ledger.claim_gap_delivery(subscription_id, today)

    def _mark_delivered(self, subscription_id: str, today: str) -> None:
        if self.ledger is None:
            self._delivered_on[subscription_id] = today

    def run(self, subscription: DigestSubscription) -> KnowledgeGapJobResult:
        if not subscription.enabled:
            return KnowledgeGapJobResult(
                subscription_id=subscription.id,
                user_id=subscription.user_id,
                channel=subscription.channel,
                target_id=subscription.target_id,
                delivered=False,
                skipped=True,
            )

        today = local_now().date().isoformat()

        try:
            report = self.use_case.inspect(subscription.user_id)
            gaps = report.gaps
        except Exception as exc:
            logger.exception("Knowledge gap detection failed user_id=%s", subscription.user_id)
            return KnowledgeGapJobResult(
                subscription_id=subscription.id,
                user_id=subscription.user_id,
                channel=subscription.channel,
                target_id=subscription.target_id,
                delivered=False,
                error=str(exc),
            )

        if not gaps:
            return KnowledgeGapJobResult(
                subscription_id=subscription.id,
                user_id=subscription.user_id,
                channel=subscription.channel,
                target_id=subscription.target_id,
                delivered=False,
                gaps_found=0,
                skipped=True,
            )

        # Claim only once we actually have something to deliver, so a gap-free
        # earlier run does not burn the day's slot and block a real gap later.
        if self._already_delivered_today(subscription.id, today):
            return KnowledgeGapJobResult(
                subscription_id=subscription.id,
                user_id=subscription.user_id,
                channel=subscription.channel,
                target_id=subscription.target_id,
                delivered=False,
                gaps_found=len(gaps),
                skipped=True,
            )

        result = self.delivery_router.send(
            DeliveryTarget(
                channel=subscription.channel,
                target_type=subscription.target_type,
                target_id=subscription.target_id,
            ),
            DeliveryMessage(
                title="知识缺口提醒",
                text=report.text,
                metadata={"user_id": subscription.user_id, "kind": "knowledge_gap"},
            ),
        )
        if result.ok:
            self._mark_delivered(subscription.id, today)
            logger.info(
                "Knowledge gap question delivered subscription_id=%s gaps=%s",
                subscription.id,
                len(gaps),
            )
        else:
            logger.warning(
                "Knowledge gap delivery failed subscription_id=%s error=%s",
                subscription.id,
                result.error,
            )
        return KnowledgeGapJobResult(
            subscription_id=subscription.id,
            user_id=subscription.user_id,
            channel=subscription.channel,
            target_id=subscription.target_id,
            delivered=result.ok,
            gaps_found=len(gaps),
            error=result.error,
        )

class KnowledgeGapScheduler:
    """Select due subscriptions and run the gap job for each."""

    def __init__(
        self,
        subscription_store: KnowledgeGapSubscriptionStore,
        job: KnowledgeGapJob,
    ) -> None:
        self.subscription_store = subscription_store
        self.job = job

    def due_subscriptions(self, now: datetime | None = None) -> list[DigestSubscription]:
        current = now or local_now()
        return [
            subscription
            for subscription in self.subscription_store.list_subscriptions(enabled_only=True)
            if is_subscription_due(subscription, current)
        ]

    def run_due(self, now: datetime | None = None) -> list[KnowledgeGapJobResult]:
        results: list[KnowledgeGapJobResult] = []
        for subscription in self.due_subscriptions(now):
            try:
                results.append(self.job.run(subscription))
            except Exception as exc:
                logger.exception(
                    "Knowledge gap scheduled job failed subscription_id=%s",
                    subscription.id,
                )
                results.append(KnowledgeGapJobResult(
                    subscription_id=subscription.id,
                    user_id=subscription.user_id,
                    channel=subscription.channel,
                    target_id=subscription.target_id,
                    delivered=False,
                    error=str(exc),
                ))
        return results


class KnowledgeGapJobRunner:
    """In-process scheduler loop for deployments that do not use cron."""

    def __init__(
        self,
        scheduler: KnowledgeGapScheduler,
        *,
        tick_seconds: int = 300,
    ) -> None:
        self.scheduler = scheduler
        self.tick_seconds = max(10, tick_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            name="knowledge-gap-runner",
            daemon=True,
        )
        self._thread.start()
        logger.info("Knowledge gap job runner started tick_seconds=%s", self.tick_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scheduler.run_due()
            except Exception:
                logger.exception("Knowledge gap scheduler tick failed")
            self._stop.wait(self.tick_seconds)
