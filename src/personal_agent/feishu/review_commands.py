from __future__ import annotations

import re

from ..core.config import Settings
from ..review import DigestSubscription
from ..review.models import ReviewFeedbackOutcome
from .models import FeishuIncomingMessage


def is_digest_command(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {
        "digest",
        "/digest",
        "今日简报",
        "今天简报",
        "知识简报",
        "复习一下",
        "今日复习",
        "今天复习",
    }


def parse_review_feedback(text: str) -> tuple[str, ReviewFeedbackOutcome] | None:
    normalized = text.strip().lower()
    match = re.match(r"^(r\d+)\s*[:：,，.。-]?\s*(.+)$", normalized)
    if not match:
        return None
    short_id = match.group(1).upper()
    outcome_text = match.group(2).strip()
    remembered = {"记得", "会了", "掌握", "remembered", "remember", "ok", "yes", "y"}
    forgotten = {"忘了", "不会", "没记住", "forgotten", "forgot", "no", "n"}
    later = {"稍后", "晚点", "later", "skip"}
    if outcome_text in remembered:
        return short_id, "remembered"
    if outcome_text in forgotten:
        return short_id, "forgotten"
    if outcome_text in later:
        return short_id, "later"
    return None


def parse_digest_subscription_command(text: str) -> tuple[str, str | None] | None:
    normalized = text.strip().lower()
    if normalized in {"订阅简报", "订阅复习", "订阅digest", "/digest subscribe", "digest subscribe"}:
        return "subscribe", None
    if normalized in {"取消订阅简报", "取消订阅复习", "取消订阅digest", "/digest unsubscribe", "digest unsubscribe"}:
        return "unsubscribe", None
    match = re.match(r"^(?:简报时间|复习时间|digest time)\s+([0-2]?\d:[0-5]\d)$", normalized)
    if match:
        hour_text, minute_text = match.group(1).split(":", 1)
        hour = int(hour_text)
        if 0 <= hour <= 23:
            return "subscribe", f"{hour:02d}:{minute_text}"
    return None


def handle_digest_subscription_command(
    incoming_message: FeishuIncomingMessage,
    *,
    action: str,
    schedule_time: str | None,
    settings: Settings,
    store,
) -> str:
    chat_id = incoming_message.chat_id or incoming_message.metadata.get("chat_id") or ""
    if not chat_id:
        return "当前消息缺少飞书会话 ID，暂时无法管理简报订阅。"
    subscription_id = f"feishu:{incoming_message.user_id}:{chat_id}"
    existing = store.get_subscription(subscription_id)
    if action == "unsubscribe":
        if existing is None:
            existing = DigestSubscription(
                id=subscription_id,
                user_id=incoming_message.user_id,
                target_id=chat_id,
                enabled=False,
            )
        store.upsert_subscription(existing.model_copy(update={"enabled": False}))
        return "已取消当前会话的复习 Digest 订阅。"

    updates = {
        "user_id": incoming_message.user_id,
        "channel": "feishu",
        "target_type": "chat_id",
        "target_id": chat_id,
        "enabled": True,
    }
    if schedule_time:
        updates["schedule_time"] = schedule_time
    if existing:
        subscription = existing.model_copy(update=updates)
    else:
        subscription = DigestSubscription(
            id=subscription_id,
            schedule_time=str(updates.pop("schedule_time", settings.review_digest.schedule_time)),
            timezone=settings.review_digest.timezone,
            **updates,
        )
    saved = store.upsert_subscription(subscription)
    return f"已订阅当前会话的复习 Digest，发送时间 {saved.schedule_time}（{saved.timezone}）。"
