from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from personal_agent.kernel.models import local_now
from personal_agent.application.review.jobs import ReviewDigestJob
from personal_agent.application.review.models import DigestSubscription, ReviewDigestJobResult

logger = logging.getLogger(__name__)


class ReviewDigestSubscriptionStore(Protocol):
    def list_subscriptions(self, *, enabled_only: bool = True) -> list[DigestSubscription]:
        ...


class ReviewDigestScheduler:
    """Select due review digest subscriptions and run the internal job."""

    def __init__(
        self,
        subscription_store: ReviewDigestSubscriptionStore,
        job: ReviewDigestJob,
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

    def run_due(self, now: datetime | None = None) -> list[ReviewDigestJobResult]:
        results: list[ReviewDigestJobResult] = []
        for subscription in self.due_subscriptions(now):
            try:
                results.append(self.job.run(subscription))
            except Exception as exc:
                logger.exception(
                    "Review digest scheduled job failed subscription_id=%s",
                    subscription.id,
                )
                results.append(ReviewDigestJobResult(
                    subscription_id=subscription.id,
                    user_id=subscription.user_id,
                    channel=subscription.channel,
                    target_id=subscription.target_id,
                    delivered=False,
                    error=str(exc),
                ))
        return results


class ReviewDigestJobRunner:
    """Small in-process scheduler loop for deployments that do not use cron."""

    def __init__(
        self,
        scheduler: ReviewDigestScheduler,
        *,
        tick_seconds: int = 60,
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
            name="review-digest-runner",
            daemon=True,
        )
        self._thread.start()
        logger.info("Review digest job runner started tick_seconds=%s", self.tick_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scheduler.run_due()
            except Exception:
                logger.exception("Review digest scheduler tick failed")
            self._stop.wait(self.tick_seconds)


def is_subscription_due(subscription: DigestSubscription, now: datetime) -> bool:
    try:
        zone = ZoneInfo(subscription.timezone)
    except ZoneInfoNotFoundError:
        logger.warning(
            "Review digest subscription has invalid timezone subscription_id=%s timezone=%s",
            subscription.id,
            subscription.timezone,
        )
        return False
    local = now.astimezone(zone)
    hour, minute = _parse_schedule_time(subscription.schedule_time)
    return (local.hour, local.minute) >= (hour, minute)


def _parse_schedule_time(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.strip().split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return 9, 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return 9, 0
    return hour, minute
