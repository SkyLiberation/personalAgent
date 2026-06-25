from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from personal_agent.application.review import DigestSubscription, ReviewDigestScheduler
from personal_agent.application.review.models import ReviewDigestJobResult
from personal_agent.application.review.scheduler import is_subscription_due


def test_subscription_due_respects_timezone_and_schedule_time():
    subscription = DigestSubscription(
        id="sub-1",
        user_id="alice",
        target_id="chat-1",
        schedule_time="09:00",
        timezone="Asia/Shanghai",
    )

    assert is_subscription_due(subscription, datetime(2026, 6, 16, 0, 59, tzinfo=ZoneInfo("UTC"))) is False
    assert is_subscription_due(subscription, datetime(2026, 6, 16, 1, 0, tzinfo=ZoneInfo("UTC"))) is True


def test_scheduler_runs_due_subscriptions_only():
    due = DigestSubscription(
        id="due",
        user_id="alice",
        target_id="chat-1",
        schedule_time="09:00",
        timezone="Asia/Shanghai",
    )
    pending = DigestSubscription(
        id="pending",
        user_id="alice",
        target_id="chat-2",
        schedule_time="10:00",
        timezone="Asia/Shanghai",
    )

    class Store:
        def list_subscriptions(self, *, enabled_only: bool = True):
            return [due, pending]

    class Job:
        def __init__(self) -> None:
            self.ran: list[str] = []

        def run(self, subscription):
            self.ran.append(subscription.id)
            return ReviewDigestJobResult(
                subscription_id=subscription.id,
                user_id=subscription.user_id,
                channel=subscription.channel,
                target_id=subscription.target_id,
                delivered=True,
            )

    job = Job()
    scheduler = ReviewDigestScheduler(Store(), job)

    results = scheduler.run_due(datetime(2026, 6, 16, 1, 30, tzinfo=ZoneInfo("UTC")))

    assert [result.subscription_id for result in results] == ["due"]
    assert job.ran == ["due"]
