from __future__ import annotations

from unittest.mock import MagicMock

from personal_agent.application.runtime_results import DigestResult
from personal_agent.application.conversation import (
    ConversationMessage,
    ConversationTurnView,
)
from personal_agent.kernel.config import Settings
from personal_agent.adapters.feishu.models import FeishuIncomingMessage
from personal_agent.adapters.feishu.service import FeishuService
from personal_agent.application.review import DigestSubscription
from personal_agent.kernel.contracts.review import ReviewFeedbackResult


def test_feishu_text_enters_canonical_conversation_with_visible_thread_context(temp_dir):
    agent_service = MagicMock()
    agent_service.converse.return_value = ConversationTurnView(
        interaction_run_ref="irun-feishu",
        conversation_id="chat-1",
        disposition="answer",
        message=ConversationMessage(role="assistant", content="完成"),
    )
    service = FeishuService(Settings(data_dir=temp_dir), agent_service)
    service.fetch_recent_messages = MagicMock(
        return_value=[{"role": "user", "content": "前文"}]
    )

    service.process_incoming_message(
        FeishuIncomingMessage(
            text="帮我总结一下群聊",
            user_id="default",
            session_id="chat-1",
            message_id="msg-1",
            metadata={"chat_id": "chat-1"},
        )
    )

    service.fetch_recent_messages.assert_called_once_with("chat-1", limit=20)
    call = agent_service.converse.call_args.kwargs
    assert call["conversation_id"] == "chat-1"
    assert call["user_id"] == "default"
    assert call["source_platform"] == "feishu"
    assert [item.content for item in call["messages"]] == ["前文", "帮我总结一下群聊"]


def test_feishu_digest_command_short_circuits_entry(temp_dir):
    agent_service = MagicMock()
    agent_service.digest.return_value = DigestResult(message="今日知识简报\n- A")
    service = FeishuService(Settings(data_dir=temp_dir), agent_service)

    reply = service.process_incoming_message(
        FeishuIncomingMessage(
            text="今日简报",
            user_id="alice",
            session_id="chat-1",
            message_id="msg-1",
            metadata={"chat_id": "chat-1"},
        )
    )

    assert reply == "今日知识简报\n- A"
    agent_service.digest.assert_called_once_with("alice")
    agent_service.converse.assert_not_called()


def test_feishu_review_feedback_short_circuits_entry(temp_dir):
    agent_service = MagicMock()
    feedback_use_case = MagicMock()
    feedback_use_case.apply_from_delivery_short_id.return_value = ReviewFeedbackResult(
        ok=True,
        short_id="R1",
        outcome="remembered",
        review_card_id="card-1",
        delivery_id="delivery-1",
        message="已记录：这条你记得。",
    )
    service = FeishuService(
        Settings(data_dir=temp_dir),
        agent_service,
        review_feedback_use_case=feedback_use_case,
    )

    reply = service.process_incoming_message(
        FeishuIncomingMessage(
            text="R1 记得",
            user_id="alice",
            session_id="chat-1",
            chat_id="chat-1",
            message_id="msg-1",
            metadata={"chat_id": "chat-1"},
        )
    )

    assert reply == "已记录：这条你记得。"
    feedback_use_case.apply_from_delivery_short_id.assert_called_once_with(
        user_id="alice",
        target_id="chat-1",
        short_id="R1",
        outcome="remembered",
        source_channel="feishu",
        source_message_id="msg-1",
    )
    agent_service.converse.assert_not_called()


def test_feishu_digest_subscription_command_upserts_current_chat(temp_dir):
    class Store:
        def __init__(self) -> None:
            self.items: dict[str, DigestSubscription] = {}

        def get_subscription(self, subscription_id: str):
            return self.items.get(subscription_id)

        def upsert_subscription(self, subscription: DigestSubscription):
            self.items[subscription.id] = subscription
            return subscription

    agent_service = MagicMock()
    store = Store()
    service = FeishuService(
        Settings(data_dir=temp_dir),
        agent_service,
        review_digest_store=store,
    )

    reply = service.process_incoming_message(
        FeishuIncomingMessage(
            text="简报时间 08:30",
            user_id="alice",
            session_id="chat-1",
            chat_id="chat-1",
            message_id="msg-1",
            metadata={"chat_id": "chat-1"},
        )
    )

    assert "08:30" in reply
    subscription = store.items["feishu:alice:chat-1"]
    assert subscription.enabled is True
    assert subscription.target_id == "chat-1"
    assert subscription.schedule_time == "08:30"
    agent_service.converse.assert_not_called()
