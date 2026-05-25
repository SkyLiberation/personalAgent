from __future__ import annotations

from unittest.mock import MagicMock

from personal_agent.core.config import Settings
from personal_agent.core.models import EntryInput
from personal_agent.feishu.models import FeishuIncomingMessage
from personal_agent.feishu.service import FeishuService


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
