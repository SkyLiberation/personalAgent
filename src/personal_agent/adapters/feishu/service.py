from __future__ import annotations

import logging
import json
import re
import threading

import lark_oapi as lark

from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.application.conversation import ConversationMessage
from personal_agent.kernel.contracts.scope import (
    AuthenticatedPrincipal,
    SecurityScope,
)
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.application.review import ReviewFeedbackUseCase
from personal_agent.application.research import ResearchFeedback
from personal_agent.adapters.feishu.client import FeishuClientMixin
from personal_agent.adapters.feishu.models import FeishuIncomingMessage
from personal_agent.adapters.feishu.review_commands import (
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

        artifacts: list[ResourceRef] = []
        if incoming_message.message_type == "file":
            artifact = self._attach_downloaded_file(incoming_message, metadata)
            if artifact is not None:
                artifacts.append(artifact)

        history = self.fetch_recent_messages(
            incoming_message.chat_id or metadata.get("chat_id", ""),
            limit=20,
        ) if (incoming_message.chat_id or metadata.get("chat_id")) else []
        messages = [
            ConversationMessage(role=item["role"], content=item["content"])
            for item in history
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
        current_text = incoming_message.text.strip()
        if artifacts:
            current_text += "\n\n附件 ResourceRef：" + json.dumps(
                [item.model_dump(mode="json") for item in artifacts],
                ensure_ascii=False,
            )
        if not messages or messages[-1].role != "user" or messages[-1].content != current_text:
            messages.append(ConversationMessage(role="user", content=current_text))
        conversation_result = self.agent_service.converse(
            conversation_id=incoming_message.session_id,
            messages=messages,
            principal=AuthenticatedPrincipal(
                tenant_id="feishu",
                user_id=incoming_message.user_id,
            ),
            security_scope=SecurityScope(
                tenant_id="feishu",
                workspace_id=incoming_message.session_id,
            ),
            source_platform="feishu",
        )
        reply_text = conversation_result.message.content
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
        research_feedback = _parse_research_feedback(incoming_message.text)
        if research_feedback is not None:
            short_id, action = research_feedback
            target_id = incoming_message.chat_id or metadata.get("chat_id") or ""
            found = self.agent_service.research_store.find_latest_delivered_item(
                user_id=incoming_message.user_id,
                target_id=target_id,
                short_id=short_id,
            )
            if found is not None:
                digest, run, event = found
                if action == "expand":
                    reply_text = (
                        f"{event.title}\n\n{event.summary}\n\n"
                        + "\n".join(source.url for source in event.sources[:5])
                    )
                elif action == "save":
                    self.agent_service.save_research_event(
                        event.id,
                        user_id=incoming_message.user_id,
                    )
                    reply_text = f"已将 {short_id} 保存到知识库。"
                else:
                    self.agent_service.submit_research_feedback(ResearchFeedback(
                        user_id=incoming_message.user_id,
                        subscription_id=run.subscription_id,
                        run_id=run.id,
                        event_id=event.id,
                        action=action,
                        source_channel="feishu",
                        source_message_id=incoming_message.message_id,
                    ))
                    reply_text = {
                        "useful": "已记录为有用，会提高相关内容权重。",
                        "not_interested": "已记录为不感兴趣，会减少相关内容。",
                        "bookmark": "已收藏该条情报。",
                    }[action]
                self._reply_to_message(incoming_message, reply_text)
                return reply_text

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
    ) -> ResourceRef | None:
        file_key = metadata.get("file_key", "")
        if not (file_key and incoming_message.message_id):
            return None
        downloaded = self.download_file(incoming_message.message_id, file_key)
        if not downloaded:
            return None
        file_bytes, filename = downloaded
        upload_dir = self.settings.data_dir / "uploads"
        artifact = self.agent_service.artifact_service.save_upload(
            filename=filename,
            content_type=None,
            file_bytes=file_bytes,
            uploads_dir=upload_dir,
            principal=AuthenticatedPrincipal(
                tenant_id="feishu",
                user_id=incoming_message.user_id,
            ),
            security_scope=SecurityScope(
                tenant_id="feishu",
                workspace_id=incoming_message.user_id,
            ),
        )
        metadata["artifact_id"] = artifact.resource_id
        logger.info(
            "Feishu file downloaded event_id=%s file_key=%s artifact_id=%s",
            incoming_message.event_id,
            file_key,
            artifact.resource_id,
        )
        return artifact

def _parse_research_feedback(text: str):
    match = re.fullmatch(
        r"\s*(N\d+)\s*(展开|有用|不感兴趣|收藏|入库)\s*",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    action = {
        "展开": "expand",
        "有用": "useful",
        "不感兴趣": "not_interested",
        "收藏": "bookmark",
        "入库": "save",
    }[match.group(2)]
    return match.group(1).upper(), action
