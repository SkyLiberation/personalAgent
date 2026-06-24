from __future__ import annotations

import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import ResearchSubscription, utc_now

logger = logging.getLogger(__name__)


def subscription_due(subscription: ResearchSubscription, now: datetime | None = None) -> bool:
    if not subscription.enabled:
        return False
    try:
        local = (now or utc_now()).astimezone(ZoneInfo(subscription.schedule.timezone))
    except ZoneInfoNotFoundError:
        return False
    hour, minute = map(int, subscription.schedule.schedule_time.split(":"))
    if (local.hour, local.minute) < (hour, minute):
        return False
    if subscription.last_window_end is not None:
        previous = subscription.last_window_end.astimezone(local.tzinfo)
        if previous.date() == local.date():
            return False
    frequency = subscription.schedule.frequency
    if frequency == "weekdays" and local.weekday() >= 5:
        return False
    if frequency == "weekly" and local.weekday() not in subscription.schedule.weekdays:
        return False
    return True


def scheduled_window_end(
    subscription: ResearchSubscription, now: datetime | None = None
) -> datetime:
    current = now or utc_now()
    local = current.astimezone(ZoneInfo(subscription.schedule.timezone))
    hour, minute = map(int, subscription.schedule.schedule_time.split(":"))
    return local.replace(hour=hour, minute=minute, second=0, microsecond=0).astimezone(
        current.tzinfo
    )


class ResearchScheduler:
    def __init__(self, store, service) -> None:
        self.store = store
        self.service = service

    def enqueue_due(self, now: datetime | None = None):
        current = now or utc_now()
        runs = []
        for subscription in self.store.list_subscriptions(enabled_only=True):
            if subscription_due(subscription, current):
                runs.append(self.service.enqueue_subscription_run(
                    subscription,
                    window_end=scheduled_window_end(subscription, current),
                    trigger_type="scheduled",
                ))
        return runs


class ResearchSchedulerRunner:
    def __init__(self, scheduler: ResearchScheduler, *, tick_seconds: int = 60) -> None:
        self.scheduler = scheduler
        self.tick_seconds = max(10, tick_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="research-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scheduler.enqueue_due()
            except Exception:
                logger.exception("Research scheduler tick failed")
            self._stop.wait(self.tick_seconds)
