from __future__ import annotations

from unittest.mock import MagicMock

from personal_agent.agent.runtime_results import DigestResult
from personal_agent.core.config import Settings
from personal_agent.core.models import EntryInput
from personal_agent.feishu.models import FeishuIncomingMessage
from personal_agent.feishu.service import FeishuService
from personal_agent.review import DigestSubscription
from personal_agent.review.models import ReviewFeedbackResult


def test_feishu_entry_does_not_preclassify_or_prefetch_thread_messages(temp_dir):
    agent_service = MagicMock()
    agent_service.entry.return_value.reply_text = "完成"
    service = FeishuService(Settings(data_dir=temp_dir), agent_service)
    service.fetch_recent_messages = MagicMock(return_value=[])

    service.process_incoming_message(
        FeishuIncomingMessage(
            text="帮我总结一下群聊",
            user_id="default",
            session_id="chat-1",
            message_id="msg-1",
            metadata={"chat_id": "chat-1"},
        )
    )

    service.fetch_recent_messages.assert_not_called()
    entry_input = agent_service.entry.call_args.args[0]
    assert entry_input.source_platform == "feishu"
    assert entry_input.metadata == {"chat_id": "chat-1"}


def test_feishu_registered_thread_loader_fetches_only_feishu_chat_context(temp_dir):
    agent_service = MagicMock()
    service = FeishuService(Settings(data_dir=temp_dir), agent_service)
    service.fetch_recent_messages = MagicMock(
        return_value=[{"role": "user", "content": "待总结内容"}]
    )
    loader = agent_service.set_thread_message_loader.call_args.args[0]

    messages = loader(
        EntryInput(
            text="总结群聊",
            source_platform="feishu",
            metadata={"chat_id": "chat-1"},
        ),
        20,
    )
    not_feishu = loader(
        EntryInput(
            text="总结群聊",
            source_platform="web",
            metadata={"chat_id": "chat-1"},
        ),
        20,
    )

    assert messages == [{"role": "user", "content": "待总结内容"}]
    assert not_feishu == []
    service.fetch_recent_messages.assert_called_once_with("chat-1", limit=20)


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
    agent_service.entry.assert_not_called()


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
    agent_service.entry.assert_not_called()


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
    agent_service.entry.assert_not_called()
