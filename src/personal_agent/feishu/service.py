from __future__ import annotations

import logging
import threading

import lark_oapi as lark

from ..agent.service import AgentService
from ..core.config import Settings
from ..core.models import EntryInput
from ..review import ReviewFeedbackUseCase
from .client import FeishuClientMixin
from .models import FeishuIncomingMessage
from .review_commands import (
    handle_digest_subscription_command,
    is_digest_command,
    parse_digest_subscription_command,
    parse_review_feedback,
)

logger = logging.getLogger(__name__)


class FeishuService(FeishuClientMixin):
    def __init__(
        self,
        settings: Settings,
        agent_service: AgentService,
        review_feedback_use_case: ReviewFeedbackUseCase | None = None,
        review_digest_store=None,
    ) -> None:
        self.settings = settings
        self.agent_service = agent_service
        self.review_feedback_use_case = review_feedback_use_case
        self.review_digest_store = review_digest_store
        self.agent_service.set_thread_message_loader(self._load_thread_messages_for_entry)
        self._client: lark.Client | None = None
        self._ws_client: lark.ws.Client | None = None
        self._ws_thread: threading.Thread | None = None
        self._ws_started = False
        self._ws_lock = threading.Lock()
        self._processed_event_ids: dict[str, float] = {}
        self._processed_lock = threading.Lock()

    def process_incoming_message(self, incoming_message: FeishuIncomingMessage) -> str:
        logger.info(
            "Feishu message processing started event_id=%s message_id=%s session_id=%s",
            incoming_message.event_id,
            incoming_message.message_id,
            incoming_message.session_id,
        )
        metadata = dict(incoming_message.metadata)

        if incoming_message.message_type == "text":
            command_reply = self._try_handle_text_command(incoming_message, metadata)
            if command_reply is not None:
                return command_reply

        if incoming_message.message_type == "file":
            self._attach_downloaded_file(incoming_message, metadata)

        entry_result = self.agent_service.entry(
            EntryInput(
                text=incoming_message.text,
                user_id=incoming_message.user_id,
                session_id=incoming_message.session_id,
                source_platform="feishu",
                source_type=incoming_message.message_type,
                source_ref=incoming_message.message_id,
                metadata=metadata,
            )
        )
        reply_text = entry_result.reply_text
        self._reply_to_message(incoming_message, reply_text)
        logger.info(
            "Feishu message processed event_id=%s message_id=%s reply_length=%s",
            incoming_message.event_id,
            incoming_message.message_id,
            len(reply_text),
        )
        return reply_text

    def _try_handle_text_command(
        self,
        incoming_message: FeishuIncomingMessage,
        metadata: dict[str, str],
    ) -> str | None:
        subscription_command = parse_digest_subscription_command(incoming_message.text)
        if subscription_command is not None and self.review_digest_store is not None:
            action, schedule_time = subscription_command
            reply_text = handle_digest_subscription_command(
                incoming_message,
                action=action,
                schedule_time=schedule_time,
                settings=self.settings,
                store=self.review_digest_store,
            )
            self._reply_to_message(incoming_message, reply_text)
            return reply_text

        if is_digest_command(incoming_message.text):
            digest_result = self.agent_service.digest(incoming_message.user_id)
            reply_text = digest_result.message
            self._reply_to_message(incoming_message, reply_text)
            logger.info(
                "Feishu digest command processed event_id=%s message_id=%s user_id=%s reply_length=%s",
                incoming_message.event_id,
                incoming_message.message_id,
                incoming_message.user_id,
                len(reply_text),
            )
            return reply_text

        feedback = parse_review_feedback(incoming_message.text)
        if feedback is not None and self.review_feedback_use_case is not None:
            short_id, outcome = feedback
            target_id = incoming_message.chat_id or metadata.get("chat_id") or ""
            result = self.review_feedback_use_case.apply_from_delivery_short_id(
                user_id=incoming_message.user_id,
                target_id=target_id,
                short_id=short_id,
                outcome=outcome,
                source_channel="feishu",
                source_message_id=incoming_message.message_id,
            )
            reply_text = result.message if result.ok else result.error or "复习反馈处理失败。"
            self._reply_to_message(incoming_message, reply_text)
            logger.info(
                "Feishu review feedback processed event_id=%s message_id=%s user_id=%s short_id=%s ok=%s",
                incoming_message.event_id,
                incoming_message.message_id,
                incoming_message.user_id,
                short_id,
                result.ok,
            )
            return reply_text

        return None

    def _attach_downloaded_file(
        self,
        incoming_message: FeishuIncomingMessage,
        metadata: dict[str, str],
    ) -> None:
        file_key = metadata.get("file_key", "")
        if not (file_key and incoming_message.message_id):
            return
        downloaded = self.download_file(incoming_message.message_id, file_key)
        if not downloaded:
            return
        file_bytes, filename = downloaded
        upload_dir = self.settings.data_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / f"feishu_{incoming_message.message_id}_{filename}"
        file_path.write_bytes(file_bytes)
        metadata["file_path"] = str(file_path)
        metadata["original_filename"] = filename
        logger.info(
            "Feishu file downloaded event_id=%s file_key=%s path=%s",
            incoming_message.event_id,
            file_key,
            file_path,
        )

    def _load_thread_messages_for_entry(
        self, entry_input: EntryInput, limit: int = 20
    ) -> list[dict[str, str]]:
        """Load Feishu chat context after the entry graph selects summarization."""
        if entry_input.source_platform != "feishu":
            return []
        chat_id = entry_input.metadata.get("chat_id", "")
        if not chat_id:
            return []
        messages = self.fetch_recent_messages(chat_id, limit=limit)
        if messages:
            logger.info(
                "Feishu thread messages loaded for summarize session_id=%s chat_id=%s count=%s",
                entry_input.session_id,
                chat_id,
                len(messages),
            )
        return messages
