from __future__ import annotations

import logging
import re
import threading

import lark_oapi as lark
from pydantic import ValidationError

from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.policy import EntryPolicyDenied
from personal_agent.application.conversation import ConversationMessage, ConversationTurnView
from personal_agent.application.conversation.errors import (
    ConversationInputError,
    ConversationOperationConflict,
    ConversationOperationNotFound,
    ConversationTurnBlocked,
    ConversationTurnPending,
    ConversationWriterBusy,
)
from personal_agent.application.conversation.service import submitted_turn_id
from personal_agent.kernel.contracts.scope import (
    AuthenticatedPrincipal,
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
        self._ws_accept_messages = False
        self._ws_message_threads: set[threading.Thread] = set()
        self._ws_lock = threading.Lock()
        self._processed_event_ids: dict[str, float] = {}
        self._processed_lock = threading.Lock()

    def process_incoming_message(self, incoming_message: FeishuIncomingMessage) -> str:
        if self.settings.policy.restricts_principals:
            sender_id = incoming_message.open_id or incoming_message.sender_user_id
            if sender_id is None:
                return "主体名单要求飞书事件包含发送者身份。"
            incoming_message = incoming_message.model_copy(update={"user_id": sender_id})
        principal = AuthenticatedPrincipal(tenant_id="feishu", user_id=incoming_message.user_id)
        try:
            self.agent_service.authorize_entry(principal, "feishu", preflight=True)
        except EntryPolicyDenied as exc:
            return str(exc)
        request_id = incoming_message.client_request_id
        if request_id is None:
            logger.warning("Feishu event is missing event_id and message_id")
            return "消息缺少飞书事件或消息 ID。"
        logger.info(
            "Feishu message processing started event_id=%s message_id=%s session_id=%s",
            incoming_message.event_id,
            incoming_message.message_id,
            incoming_message.session_id,
        )
        if incoming_message.message_type == "text":
            command_reply = self._try_handle_text_command(incoming_message, incoming_message.metadata)
            if command_reply is not None:
                return command_reply

        try:
            return self._process_conversation_message(incoming_message, principal, request_id)
        except Exception:
            with self._processed_lock:
                self._processed_event_ids.pop(request_id, None)
            raise

    def _process_conversation_message(
        self,
        incoming_message: FeishuIncomingMessage,
        principal: AuthenticatedPrincipal,
        request_id: str,
    ) -> str:
        session_id = incoming_message.session_id
        if not session_id:
            logger.warning("Feishu conversation message is missing a channel session identity")
            return "消息缺少飞书会话 ID。"
        resume_command = (
            re.fullmatch(r"\s*恢复轮次\s+((?:turn|irun)_[A-Za-z0-9_-]{1,123})\s*", incoming_message.text)
            if incoming_message.message_type == "text"
            else None
        )
        try:
            if resume_command is not None:
                result = self._resume_turn(session_id, resume_command.group(1), principal)
            else:
                result = self._submit_turn(incoming_message, principal, session_id, request_id)
                if result is None:
                    return ""
        except ConversationTurnBlocked as exc:
            reply_text = f"{exc}。可发送「恢复轮次 {exc.turn_id}」继续。"
        except ConversationWriterBusy:
            reply_text = "该会话正在处理消息，请稍后重试。"
        except (ConversationOperationNotFound, PermissionError):
            reply_text = "当前飞书会话无法访问该轮次。"
        except (ConversationInputError, ConversationOperationConflict) as exc:
            reply_text = str(exc)
        else:
            reply_text = result.message.content
        self._reply_to_message(incoming_message, reply_text)
        logger.info(
            "Feishu message processed event_id=%s message_id=%s reply_length=%s",
            incoming_message.event_id,
            incoming_message.message_id,
            len(reply_text),
        )
        return reply_text

    def _submit_turn(
        self,
        incoming_message: FeishuIncomingMessage,
        principal: AuthenticatedPrincipal,
        session_id: str,
        request_id: str,
    ) -> ConversationTurnView | None:
        turn_id = submitted_turn_id(principal, session_id, request_id)
        try:
            message = ConversationMessage(role="user", content=incoming_message.text)
        except ValidationError as exc:
            raise ConversationInputError("消息为空或超过长度限制。") from exc
        artifact_refs = self._conversation_artifact_refs(incoming_message, principal, turn_id)
        try:
            return self.agent_service.converse(
                conversation_id=session_id,
                message=message,
                client_request_id=request_id,
                create_session=None,
                principal=principal,
                source_platform="feishu",
                input_artifact_refs=artifact_refs,
            )
        except ConversationTurnPending:
            logger.info("Feishu conversation turn is already pending turn_id=%s", turn_id)
            return None

    def _resume_turn(
        self, session_id: str, turn_id: str, principal: AuthenticatedPrincipal
    ) -> ConversationTurnView:
        trace = self.agent_service.conversation_trace(turn_id, principal=principal)
        if trace is None or trace.conversation_id != session_id:
            raise ConversationOperationNotFound("轮次不存在。")
        return self.agent_service.converse(
            conversation_id=session_id,
            interaction_run_ref=turn_id,
            principal=principal,
            source_platform="feishu",
        )

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

    def _conversation_artifact_refs(
        self,
        incoming_message: FeishuIncomingMessage,
        principal: AuthenticatedPrincipal,
        turn_id: str,
    ) -> tuple[ResourceRef, ...]:
        if incoming_message.message_type != "file":
            return ()
        prior = self.agent_service.conversation_trace(turn_id, principal=principal)
        if prior is not None:
            if not prior.input_artifact_refs:
                raise ConversationOperationConflict("请求标识已绑定不同的用户输入。")
            return prior.input_artifact_refs
        file_key = incoming_message.metadata.get("file_key")
        message_id = incoming_message.message_id
        if not (file_key and message_id):
            raise ConversationInputError("消息缺少附件标识。")
        downloaded = self.download_file(message_id, file_key)
        if not downloaded:
            raise ConversationInputError("无法读取飞书附件，请重新发送文件。")
        file_bytes, filename = downloaded
        upload_dir = self.settings.data_dir / "uploads"
        artifact = self.agent_service.artifact_service.save_upload(
            filename=filename,
            content_type=None,
            file_bytes=file_bytes,
            uploads_dir=upload_dir,
            principal=principal,
            owner=principal,
        )
        logger.info(
            "Feishu file downloaded event_id=%s file_key=%s artifact_id=%s",
            incoming_message.event_id,
            file_key,
            artifact.resource_id,
        )
        return (artifact,)

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
