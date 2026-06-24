from __future__ import annotations

import logging
from typing import Protocol

from personal_agent.core.config import Settings
from personal_agent.core.models import local_now
from personal_agent.review.delivery import DeliveryRouter
from personal_agent.review.formatter import DigestFormatter
from personal_agent.review.models import (
    DeliveryMessage,
    DeliveryTarget,
    DigestSubscription,
    ReviewDigest,
    ReviewDigestJobResult,
)
from personal_agent.review.service import ReviewDigestUseCase

logger = logging.getLogger(__name__)


class DigestDeliveryLedger(Protocol):
    def reserve_delivery(self, subscription: DigestSubscription, digest_date: str) -> tuple[bool, str, str]:
        ...

    def complete_delivery(
        self,
        delivery_id: str,
        *,
        status: str,
        provider_message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        ...

    def add_delivery_items(self, delivery_id: str, digest: ReviewDigest) -> None:
        ...


class ReviewDigestJob:
    """Internal job for generating and delivering review digests."""

    def __init__(
        self,
        digest_use_case: ReviewDigestUseCase,
        delivery_router: DeliveryRouter,
        formatter: DigestFormatter | None = None,
        ledger: DigestDeliveryLedger | None = None,
    ) -> None:
        self.digest_use_case = digest_use_case
        self.delivery_router = delivery_router
        self.formatter = formatter or DigestFormatter()
        self.ledger = ledger

    def run(self, subscription: DigestSubscription) -> ReviewDigestJobResult:
        if not subscription.enabled:
            return ReviewDigestJobResult(
                subscription_id=subscription.id,
                user_id=subscription.user_id,
                channel=subscription.channel,
                target_id=subscription.target_id,
                delivered=False,
                skipped=True,
            )

        delivery_id: str | None = None
        idempotency_key: str | None = None
        if self.ledger is not None:
            digest_date = local_now().date().isoformat()
            reserved, delivery_id, idempotency_key = self.ledger.reserve_delivery(subscription, digest_date)
            if not reserved:
                logger.info(
                    "Review digest delivery skipped by idempotency subscription_id=%s key=%s",
                    subscription.id,
                    idempotency_key,
                )
                return ReviewDigestJobResult(
                    subscription_id=subscription.id,
                    user_id=subscription.user_id,
                    channel=subscription.channel,
                    target_id=subscription.target_id,
                    delivered=False,
                    skipped=True,
                    delivery_id=delivery_id,
                    idempotency_key=idempotency_key,
                )

        digest = self.digest_use_case.generate(subscription.user_id)
        if self.ledger is not None and delivery_id is not None and hasattr(self.ledger, "add_delivery_items"):
            self.ledger.add_delivery_items(delivery_id, digest)
        text = self.formatter.to_feishu_text(digest) if subscription.channel == "feishu" else self.formatter.to_text(digest)
        result = self.delivery_router.send(
            DeliveryTarget(
                channel=subscription.channel,
                target_type=subscription.target_type,
                target_id=subscription.target_id,
            ),
            DeliveryMessage(
                title="今日知识简报",
                text=text,
                metadata={"user_id": subscription.user_id},
            ),
        )
        if result.ok:
            logger.info(
                "Review digest delivered subscription_id=%s channel=%s target=%s",
                subscription.id,
                subscription.channel,
                subscription.target_id,
            )
        else:
            logger.warning(
                "Review digest delivery failed subscription_id=%s channel=%s target=%s error=%s",
                subscription.id,
                subscription.channel,
                subscription.target_id,
                result.error,
            )
        if self.ledger is not None and delivery_id is not None:
            self.ledger.complete_delivery(
                delivery_id,
                status="sent" if result.ok else "failed",
                provider_message_id=result.provider_message_id,
                error=result.error,
            )
        return ReviewDigestJobResult(
            subscription_id=subscription.id,
            user_id=subscription.user_id,
            channel=subscription.channel,
            target_id=subscription.target_id,
            delivered=result.ok,
            delivery_id=delivery_id,
            idempotency_key=idempotency_key,
            error=result.error,
        )


def subscriptions_from_settings(settings: Settings) -> list[DigestSubscription]:
    cfg = settings.review_digest
    if not cfg.enabled:
        return []
    return [
        DigestSubscription(
            id=f"config:feishu:{index}:{chat_id}",
            user_id=cfg.user_id,
            channel="feishu",
            target_type="chat_id",
            target_id=chat_id,
            schedule_time=cfg.schedule_time,
            timezone=cfg.timezone,
            enabled=True,
        )
        for index, chat_id in enumerate(cfg.feishu_chat_ids)
    ]
