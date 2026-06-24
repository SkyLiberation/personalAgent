from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

from personal_agent.core.models import ReviewCard, local_now
from personal_agent.memory import MemoryFacade
from personal_agent.review.formatter import DigestFormatter
from personal_agent.review.models import ReviewDigest, ReviewDigestSection, ReviewFeedbackOutcome, ReviewFeedbackResult

if TYPE_CHECKING:
    from personal_agent.graphiti.store import GraphitiStore

logger = logging.getLogger(__name__)


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

    def __init__(
        self,
        memory: MemoryFacade,
        formatter: DigestFormatter | None = None,
        graph_store: "GraphitiStore | None" = None,
    ) -> None:
        self.memory = memory
        self.formatter = formatter or DigestFormatter()
        self.graph_store = graph_store

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

        growth = self._knowledge_growth_section(user_id)
        if growth is not None:
            sections.append(growth)

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

    def _knowledge_growth_section(self, user_id: str) -> ReviewDigestSection | None:
        """Summarize knowledge growth: a note-count trend plus graph topology.

        The trend line (this week vs last week) is computed from local note
        timestamps and is always available. Graph stats are appended only when
        the graph is configured/reachable. The whole section is skipped only
        when there is neither growth nor a graph — so the digest still delivers.
        Follows the project rule that graph failures never block the local path.
        """
        items: list[str] = []

        trend = self._note_trend_line(user_id)
        if trend:
            items.append(trend)

        graph_items = self._graph_growth_items(user_id)
        items.extend(graph_items)

        if not items:
            return None
        return ReviewDigestSection(title="知识增长：", items=items)

    def _note_trend_line(self, user_id: str) -> str | None:
        """This-week vs last-week note counts from local note timestamps."""
        try:
            notes = self.memory.list_notes(user_id, include_chunks=False)
        except Exception:
            logger.warning("Knowledge growth trend skipped: list_notes failed", exc_info=True)
            return None
        if not notes:
            return None
        now = local_now()
        week = timedelta(days=7)
        this_week = sum(1 for n in notes if n.created_at and now - n.created_at <= week)
        last_week = sum(
            1 for n in notes
            if n.created_at and week < now - n.created_at <= 2 * week
        )
        if this_week == 0 and last_week == 0:
            return None
        delta = this_week - last_week
        if delta > 0:
            arrow = f"↑{delta}"
        elif delta < 0:
            arrow = f"↓{abs(delta)}"
        else:
            arrow = "持平"
        return f"本周新增 {this_week} 条笔记（上周 {last_week} 条，{arrow}）。"

    def _graph_growth_items(self, user_id: str) -> list[str]:
        if self.graph_store is None:
            return []
        try:
            topology = self.graph_store.get_topology(user_id)
        except Exception:
            logger.warning("Knowledge growth graph items skipped: get_topology failed", exc_info=True)
            return []
        if topology.get("error"):
            return []

        nodes = topology.get("nodes") or []
        links = topology.get("links") or []
        if not nodes:
            return []

        # Surface the most-connected entities (knowledge hubs) and a couple of
        # sample facts so the digest shows what the graph actually learned.
        degree: dict[str, int] = {}
        for link in links:
            for endpoint in (link.get("source"), link.get("target")):
                if endpoint:
                    degree[endpoint] = degree.get(endpoint, 0) + 1
        name_by_id = {node.get("id"): node.get("name") or "" for node in nodes}
        ranked = sorted(degree.items(), key=lambda kv: kv[1], reverse=True)
        top_names = [name_by_id.get(node_id, "") for node_id, _ in ranked if name_by_id.get(node_id)]

        items = [f"知识图谱已有 {len(nodes)} 个实体、{len(links)} 条关联。"]
        if top_names:
            items.append("连接最密集的概念：" + "、".join(top_names[:5]))
        sample_facts = [link.get("fact") for link in links if link.get("fact")][:3]
        items.extend(f"关联：{fact}" for fact in sample_facts)
        return items

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
