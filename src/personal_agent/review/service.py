from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from ..core.models import ReviewCard, local_now
from ..memory import MemoryFacade
from .formatter import DigestFormatter
from .models import ReviewDigest, ReviewDigestSection, ReviewFeedbackOutcome, ReviewFeedbackResult


class ReviewFeedbackStore(Protocol):
    def find_latest_delivery_item(
        self,
        *,
        user_id: str,
        target_id: str,
        short_id: str,
    ) -> dict | None:
        ...

    def record_feedback_event(
        self,
        *,
        review_card_id: str,
        user_id: str,
        delivery_id: str | None,
        outcome: ReviewFeedbackOutcome,
        source_channel: str,
        source_message_id: str | None = None,
    ) -> str:
        ...


class ReviewDigestUseCase:
    """Generate review digests from long-term memory."""

    def __init__(self, memory: MemoryFacade, formatter: DigestFormatter | None = None) -> None:
        self.memory = memory
        self.formatter = formatter or DigestFormatter()

    def generate(self, user_id: str, *, recent_limit: int = 5) -> ReviewDigest:
        recent_notes = self.memory.list_recent_notes(user_id, limit=recent_limit)
        due_cards = self.memory.due_reviews(user_id)
        sections: list[ReviewDigestSection] = []

        if recent_notes:
            sections.append(ReviewDigestSection(
                title="最近新增笔记：",
                items=[
                    f"{note.body.title}: {note.body.summary}"
                    for note in recent_notes
                ],
            ))

        if due_cards:
            sections.append(ReviewDigestSection(
                title="待复习内容：",
                items=[
                    f"R{index}. {card.prompt}"
                    for index, card in enumerate(due_cards, start=1)
                ],
            ))

        empty_reason = ""
        if not recent_notes and not due_cards:
            empty_reason = "当前还没有知识记录。"

        return ReviewDigest(
            user_id=user_id,
            recent_notes=recent_notes,
            due_cards=due_cards,
            sections=sections,
            empty_reason=empty_reason,
        )

    def generate_text(self, user_id: str, *, recent_limit: int = 5) -> str:
        return self.formatter.to_text(self.generate(user_id, recent_limit=recent_limit))


class ReviewFeedbackUseCase:
    """Apply review feedback from delivery channels back into review cards."""

    def __init__(self, memory: MemoryFacade, feedback_store: ReviewFeedbackStore) -> None:
        self.memory = memory
        self.feedback_store = feedback_store

    def apply_from_delivery_short_id(
        self,
        *,
        user_id: str,
        target_id: str,
        short_id: str,
        outcome: ReviewFeedbackOutcome,
        source_channel: str,
        source_message_id: str | None = None,
    ) -> ReviewFeedbackResult:
        normalized_short_id = short_id.strip().upper()
        item = self.feedback_store.find_latest_delivery_item(
            user_id=user_id,
            target_id=target_id,
            short_id=normalized_short_id,
        )
        if item is None:
            return ReviewFeedbackResult(
                ok=False,
                short_id=normalized_short_id,
                outcome=outcome,
                error="未找到对应的复习项，请先发送或查看今日简报。",
            )
        review_card_id = str(item.get("review_card_id") or "")
        delivery_id = str(item.get("delivery_id") or "") or None
        review = self.memory.get_review(review_card_id, user_id)
        if review is None:
            return ReviewFeedbackResult(
                ok=False,
                short_id=normalized_short_id,
                outcome=outcome,
                review_card_id=review_card_id,
                delivery_id=delivery_id,
                error="对应的复习卡已不存在或不属于当前用户。",
            )

        updated = _apply_review_schedule(review, outcome)
        saved = self.memory.update_review(updated, user_id)
        if saved is None:
            return ReviewFeedbackResult(
                ok=False,
                short_id=normalized_short_id,
                outcome=outcome,
                review_card_id=review_card_id,
                delivery_id=delivery_id,
                error="复习卡更新失败。",
            )

        self.feedback_store.record_feedback_event(
            review_card_id=review_card_id,
            user_id=user_id,
            delivery_id=delivery_id,
            outcome=outcome,
            source_channel=source_channel,
            source_message_id=source_message_id,
        )
        return ReviewFeedbackResult(
            ok=True,
            short_id=normalized_short_id,
            outcome=outcome,
            review_card_id=review_card_id,
            delivery_id=delivery_id,
            message=_feedback_reply(outcome, saved.interval_days),
        )

    def apply_to_review_card(
        self,
        *,
        user_id: str,
        review_card_id: str,
        outcome: ReviewFeedbackOutcome,
        source_channel: str,
        source_message_id: str | None = None,
    ) -> ReviewFeedbackResult:
        review = self.memory.get_review(review_card_id, user_id)
        if review is None:
            return ReviewFeedbackResult(
                ok=False,
                short_id="",
                outcome=outcome,
                review_card_id=review_card_id,
                error="对应的复习卡已不存在或不属于当前用户。",
            )
        saved = self.memory.update_review(_apply_review_schedule(review, outcome), user_id)
        if saved is None:
            return ReviewFeedbackResult(
                ok=False,
                short_id="",
                outcome=outcome,
                review_card_id=review_card_id,
                error="复习卡更新失败。",
            )
        self.feedback_store.record_feedback_event(
            review_card_id=review_card_id,
            user_id=user_id,
            delivery_id=None,
            outcome=outcome,
            source_channel=source_channel,
            source_message_id=source_message_id,
        )
        return ReviewFeedbackResult(
            ok=True,
            short_id="",
            outcome=outcome,
            review_card_id=review_card_id,
            message=_feedback_reply(outcome, saved.interval_days),
        )


def _apply_review_schedule(review: ReviewCard, outcome: ReviewFeedbackOutcome) -> ReviewCard:
    now = local_now()
    if outcome == "remembered":
        interval_days = max(1, review.interval_days * 2)
    elif outcome == "forgotten":
        interval_days = 1
    else:
        interval_days = max(1, review.interval_days)

    if outcome == "later":
        due_at = now + timedelta(days=1)
    else:
        due_at = now + timedelta(days=interval_days)
    return review.model_copy(update={
        "interval_days": interval_days,
        "due_at": due_at,
        "last_reviewed_at": now,
    })


def _feedback_reply(outcome: ReviewFeedbackOutcome, interval_days: int) -> str:
    if outcome == "remembered":
        return f"已记录：这条你记得。下次约 {interval_days} 天后再复习。"
    if outcome == "forgotten":
        return "已记录：这条还不稳。明天会再安排复习。"
    return "已记录：稍后再看。明天会重新提醒。"
