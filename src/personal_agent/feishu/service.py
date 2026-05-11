from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    GetMessageResourceRequest,
    ListMessageRequest,
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from ..agent.service import AgentService
from ..core.config import Settings
from ..core.models import EntryInput
from .models import FeishuIncomingMessage, FeishuWebhookResult

logger = logging.getLogger(__name__)


class FeishuService:
    def __init__(self, settings: Settings, agent_service: AgentService) -> None:
        self.settings = settings
        self.agent_service = agent_service
        self._client: lark.Client | None = None
        self._ws_client: lark.ws.Client | None = None
        self._ws_thread: threading.Thread | None = None
        self._ws_started = False
        self._ws_lock = threading.Lock()
        self._processed_event_ids: dict[str, float] = {}
        self._processed_lock = threading.Lock()

    def handle_webhook(self, payload: dict[str, object], headers: dict[str, str] | None = None) -> FeishuWebhookResult:
        headers = headers or {}
        self._verify_request(payload, headers)

        event_type = str(payload.get("type") or "")
        if event_type == "url_verification":
            challenge = str(payload.get("challenge") or "")
            logger.info("Feishu url verification received")
            return FeishuWebhookResult(body={"challenge": challenge})

        incoming_message = self._normalize_message(payload)
        if incoming_message is None:
            logger.info("Feishu webhook ignored because message payload is empty")
            return FeishuWebhookResult()

        self.process_incoming_message(incoming_message)
        return FeishuWebhookResult(incoming_message=incoming_message)

    def parse_webhook(self, payload: dict[str, object], headers: dict[str, str] | None = None) -> FeishuWebhookResult:
        headers = headers or {}
        self._verify_request(payload, headers)

        event_type = str(payload.get("type") or "")
        if event_type == "url_verification":
            challenge = str(payload.get("challenge") or "")
            logger.info("Feishu url verification received")
            return FeishuWebhookResult(body={"challenge": challenge})

        incoming_message = self._normalize_message(payload)
        if incoming_message is None:
            logger.info("Feishu webhook ignored because message payload is empty")
            return FeishuWebhookResult()

        logger.info(
            "Feishu webhook accepted event_id=%s event_type=%s message_id=%s message_type=%s chat_id=%s",
            incoming_message.event_id,
            incoming_message.event_type,
            incoming_message.message_id,
            incoming_message.message_type,
            incoming_message.chat_id,
        )
        return FeishuWebhookResult(incoming_message=incoming_message)

    def process_incoming_message(self, incoming_message: FeishuIncomingMessage) -> str:
        logger.info(
            "Feishu message processing started event_id=%s message_id=%s session_id=%s",
            incoming_message.event_id,
            incoming_message.message_id,
            incoming_message.session_id,
        )
        metadata = dict(incoming_message.metadata)

        if incoming_message.message_type == "file":
            file_key = metadata.get("file_key", "")
            if file_key and incoming_message.message_id:
                downloaded = self.download_file(incoming_message.message_id, file_key)
                if downloaded:
                    file_bytes, filename = downloaded
                    upload_dir = self.settings.data_dir / "uploads"
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    file_path = upload_dir / f"feishu_{incoming_message.message_id}_{filename}"
                    file_path.write_bytes(file_bytes)
                    metadata["file_path"] = str(file_path)
                    metadata["original_filename"] = filename
                    logger.info(
                        "Feishu file downloaded event_id=%s file_key=%s path=%s",
                        incoming_message.event_id, file_key, file_path,
                    )

        if incoming_message.text:
            from ..agent.entry_nodes import heuristic_entry_intent
            intent, _ = heuristic_entry_intent(incoming_message.text)
            if intent == "summarize_thread":
                chat_id = metadata.get("chat_id", "")
                if chat_id:
                    thread_messages = self.fetch_recent_messages(chat_id, limit=20)
                    if thread_messages:
                        metadata["thread_messages"] = json.dumps(thread_messages, ensure_ascii=False)
                        logger.info(
                            "Feishu thread messages pre-fetched event_id=%s chat_id=%s count=%s",
                            incoming_message.event_id, chat_id, len(thread_messages),
                        )

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

    def start_event_listener(self) -> None:
        if not self.settings.feishu_enabled:
            logger.info("Skip Feishu long connection because integration is disabled")
            return
        if not (self.settings.feishu_app_id and self.settings.feishu_app_secret):
            logger.info("Skip Feishu long connection because app credentials are not configured")
            return

        with self._ws_lock:
            if self._ws_started:
                logger.info("Feishu long connection already started")
                return

            self._ws_client = lark.ws.Client(
                self.settings.feishu_app_id,
                self.settings.feishu_app_secret,
                event_handler=self._event_handler(),
                log_level=lark.LogLevel.INFO,
                domain=self.settings.feishu_base_url.rstrip("/"),
            )
            self._ws_thread = threading.Thread(
                target=self._run_event_listener,
                name="feishu-ws-listener",
                daemon=True,
            )
            self._ws_thread.start()
            self._ws_started = True
            logger.info("Feishu long connection startup requested")

    def _run_event_listener(self) -> None:
        logger.info("Feishu long connection thread started")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        lark.ws.client.loop = loop
        try:
            self._ws_client.start()
        except Exception:
            logger.exception("Feishu long connection stopped unexpectedly")
            with self._ws_lock:
                self._ws_started = False
        finally:
            loop.close()

    def _event_handler(self) -> lark.EventDispatcherHandler:
        return (
            lark.EventDispatcherHandler.builder("", "", lark.LogLevel.INFO)
            .register_p2_im_message_receive_v1(self._handle_p2_im_message_receive_v1)
            .build()
        )

    def _handle_p2_im_message_receive_v1(self, data: P2ImMessageReceiveV1) -> None:
        incoming_message = self._from_p2_message_event(data)
        if incoming_message is None:
            logger.info("Feishu long connection ignored empty message event")
            return
        if self._is_duplicate_event(incoming_message.event_id):
            logger.info(
                "Feishu long connection duplicate event ignored event_id=%s message_id=%s",
                incoming_message.event_id,
                incoming_message.message_id,
            )
            return
        logger.info(
            "Feishu long connection event accepted event_id=%s event_type=%s message_id=%s message_type=%s chat_id=%s",
            incoming_message.event_id,
            incoming_message.event_type,
            incoming_message.message_id,
            incoming_message.message_type,
            incoming_message.chat_id,
        )
        threading.Thread(
            target=self._process_long_connection_message,
            args=(incoming_message,),
            name=f"feishu-event-{incoming_message.message_id or 'unknown'}",
            daemon=True,
        ).start()

    def _process_long_connection_message(self, incoming_message: FeishuIncomingMessage) -> None:
        try:
            self.process_incoming_message(incoming_message)
        except Exception:
            logger.exception(
                "Feishu long connection background processing failed event_id=%s message_id=%s",
                incoming_message.event_id,
                incoming_message.message_id,
            )

    def _from_p2_message_event(self, data: P2ImMessageReceiveV1) -> FeishuIncomingMessage | None:
        event = data.event
        if event is None or event.message is None:
            return None

        message = event.message
        sender = event.sender
        sender_id = sender.sender_id if sender is not None else None
        header = data.header
        content = _safe_json_loads(message.content or "{}")
        metadata: dict[str, str] = {}

        if message.message_type == "text":
            text = str(content.get("text") or "").strip()
        elif message.message_type == "file":
            metadata["file_key"] = str(content.get("file_key") or "")
            text = str(content.get("file_name") or "飞书文件").strip()
        elif message.message_type == "post":
            text = _extract_post_text(content)
        else:
            text = str(content.get("text") or message.message_type or "").strip()

        chat_id = str(message.chat_id or "")
        open_id = str(sender_id.open_id or "") if sender_id is not None else ""
        sender_user_id = str(sender_id.user_id or "") if sender_id is not None else ""
        user_id = self._resolve_user_id(open_id, sender_user_id)
        metadata["chat_id"] = chat_id
        metadata["open_id"] = open_id
        if sender_user_id:
            metadata["feishu_user_id"] = sender_user_id

        return FeishuIncomingMessage(
            event_id=str(header.event_id or "") if header is not None else "",
            event_type=str(header.event_type or "") if header is not None else "im.message.receive_v1",
            chat_id=chat_id or None,
            open_id=open_id or None,
            user_id=user_id,
            session_id=chat_id or open_id or "default",
            message_id=str(message.message_id or ""),
            message_type=str(message.message_type or "text"),
            text=text,
            metadata=metadata,
        )

    def _is_duplicate_event(self, event_id: str | None, ttl_seconds: int = 300) -> bool:
        if not event_id:
            return False

        now = time.time()
        with self._processed_lock:
            expired = [key for key, ts in self._processed_event_ids.items() if now - ts > ttl_seconds]
            for key in expired:
                self._processed_event_ids.pop(key, None)

            if event_id in self._processed_event_ids:
                return True

            self._processed_event_ids[event_id] = now
            return False

    def _verify_request(self, payload: dict[str, object], headers: dict[str, str]) -> None:
        if not self.settings.feishu_enabled:
            raise PermissionError("Feishu integration is not enabled.")
        expected_token = self.settings.feishu_verification_token
        if not expected_token:
            return

        actual_token = str(
            payload.get("token")
            or _as_dict(payload.get("header")).get("token")
            or headers.get("X-Lark-Token")
            or headers.get("x-lark-token")
            or ""
        )
        if actual_token != expected_token:
            raise PermissionError("Invalid Feishu verification token.")

    def _normalize_message(self, payload: dict[str, object]) -> FeishuIncomingMessage | None:
        header = _as_dict(payload.get("header"))
        event = _as_dict(payload.get("event"))
        sender = _as_dict(event.get("sender"))
        sender_id = _as_dict(sender.get("sender_id"))
        message = _as_dict(event.get("message"))
        if not message:
            return None

        message_type = str(message.get("message_type") or "text")
        content = _safe_json_loads(str(message.get("content") or "{}"))
        metadata: dict[str, str] = {}
        text = ""

        if message_type == "text":
            text = str(content.get("text") or "").strip()
        elif message_type == "file":
            metadata["file_key"] = str(content.get("file_key") or "")
            text = str(content.get("file_name") or "飞书文件").strip()
        elif message_type == "post":
            text = _extract_post_text(content)
        else:
            text = str(content.get("text") or message_type).strip()

        chat_id = str(message.get("chat_id") or "")
        open_id = str(sender_id.get("open_id") or "")
        sender_user_id = str(sender_id.get("user_id") or "")
        session_id = chat_id or open_id or "default"
        user_id = self._resolve_user_id(open_id, sender_user_id)
        metadata["chat_id"] = chat_id
        metadata["open_id"] = open_id
        if sender_user_id:
            metadata["feishu_user_id"] = sender_user_id

        return FeishuIncomingMessage(
            event_id=str(header.get("event_id") or ""),
            event_type=str(header.get("event_type") or ""),
            chat_id=chat_id or None,
            open_id=open_id or None,
            user_id=user_id,
            session_id=session_id,
            message_id=str(message.get("message_id") or ""),
            message_type=message_type,
            text=text,
            metadata=metadata,
        )

    def _reply_to_message(self, incoming_message: FeishuIncomingMessage, reply_text: str) -> None:
        if not (self.settings.feishu_app_id and self.settings.feishu_app_secret):
            logger.info("Skip Feishu reply because app credentials are not configured event_id=%s", incoming_message.event_id)
            return

        if incoming_message.message_id:
            self._reply_via_message_id(incoming_message, reply_text)
            return

        chat_id = incoming_message.chat_id or incoming_message.metadata.get("chat_id")
        if not chat_id:
            logger.warning("Skip Feishu reply because both message_id and chat_id are missing event_id=%s", incoming_message.event_id)
            return
        self._send_via_chat_id(incoming_message, reply_text, chat_id)

    def _reply_via_message_id(self, incoming_message: FeishuIncomingMessage, reply_text: str) -> None:
        request = ReplyMessageRequest.builder() \
            .message_id(incoming_message.message_id or "") \
            .request_body(
                ReplyMessageRequestBody.builder()
                .content(json.dumps({"text": reply_text}, ensure_ascii=False))
                .msg_type("text")
                .build()
            ) \
            .build()

        response = self._client_value().im.v1.message.reply(request)
        self._ensure_success(
            response=response,
            action="reply message",
            event_id=incoming_message.event_id,
            message_id=incoming_message.message_id,
        )
        logger.info(
            "Feishu reply sent event_id=%s message_id=%s mode=reply",
            incoming_message.event_id,
            incoming_message.message_id,
        )

    def _send_via_chat_id(self, incoming_message: FeishuIncomingMessage, reply_text: str, chat_id: str) -> None:
        request = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .content(json.dumps({"text": reply_text}, ensure_ascii=False))
                .msg_type("text")
                .build()
            ) \
            .build()

        response = self._client_value().im.v1.message.create(request)
        self._ensure_success(
            response=response,
            action="create message",
            event_id=incoming_message.event_id,
            message_id=incoming_message.message_id,
            chat_id=chat_id,
        )
        logger.info(
            "Feishu reply sent event_id=%s message_id=%s chat_id=%s mode=create",
            incoming_message.event_id,
            incoming_message.message_id,
            chat_id,
        )

    def _client_value(self) -> lark.Client:
        if self._client is None:
            self._client = lark.Client.builder() \
                .app_id(self.settings.feishu_app_id or "") \
                .app_secret(self.settings.feishu_app_secret or "") \
                .domain(self.settings.feishu_base_url.rstrip("/")) \
                .log_level(lark.LogLevel.INFO) \
                .build()
        return self._client

    def _ensure_success(
        self,
        response: object,
        action: str,
        event_id: str | None,
        message_id: str | None,
        chat_id: str | None = None,
    ) -> None:
        if response.success():
            return

        detail = {
            "code": response.code,
            "msg": response.msg,
            "log_id": response.get_log_id(),
            "event_id": event_id,
            "message_id": message_id,
            "chat_id": chat_id,
        }
        logger.error("Feishu SDK %s failed detail=%s", action, detail)
        raise RuntimeError(f"Feishu SDK {action} failed: {detail}")

    def download_file(self, message_id: str, file_key: str) -> tuple[bytes, str] | None:
        """Download file binary from Feishu. Returns (file_bytes, filename) or None."""
        if not (self.settings.feishu_app_id and self.settings.feishu_app_secret):
            logger.warning("Skip Feishu file download because app credentials are not configured")
            return None
        try:
            request = GetMessageResourceRequest.builder() \
                .message_id(message_id) \
                .file_key(file_key) \
                .type("file") \
                .build()
            response = self._client_value().im.v1.message_resource.get(request)
            if not response.success():
                logger.error(
                    "Feishu file download failed code=%s msg=%s message_id=%s file_key=%s",
                    response.code, response.msg, message_id, file_key,
                )
                return None
            filename = response.file_name or file_key
            return response.file, filename
        except Exception:
            logger.exception(
                "Feishu file download exception message_id=%s file_key=%s", message_id, file_key
            )
            return None

    def fetch_recent_messages(self, chat_id: str, limit: int = 20) -> list[dict[str, str]]:
        """Fetch recent messages from a Feishu chat. Returns list of {role, content} dicts."""
        if not (self.settings.feishu_app_id and self.settings.feishu_app_secret):
            logger.warning("Skip Feishu message fetch because app credentials are not configured")
            return []
        try:
            request = ListMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .receive_id(chat_id) \
                .page_size(min(limit, 50)) \
                .sort_type("ByCreateTimeDesc") \
                .build()
            response = self._client_value().im.v1.message.list(request)
            if not response.success():
                logger.error(
                    "Feishu message list failed code=%s msg=%s chat_id=%s",
                    response.code, response.msg, chat_id,
                )
                return []
            messages: list[dict[str, str]] = []
            items = response.data.items if response.data else []
            for item in reversed(items):
                if item.msg_type == "text":
                    content = _safe_json_loads(item.body.content if item.body else "{}")
                    text = str(content.get("text") or "").strip()
                    if text:
                        role = "user" if item.sender.id != "bot" else "assistant"
                        messages.append({"role": role, "content": text})
            return messages
        except Exception:
            logger.exception("Feishu message fetch exception chat_id=%s", chat_id)
            return []

    def _resolve_user_id(self, open_id: str, sender_user_id: str) -> str:
        if self.settings.feishu_use_default_user:
            return self.settings.default_user
        return open_id or sender_user_id or self.settings.default_user


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _safe_json_loads(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_post_text(content: dict[str, object]) -> str:
    lines: list[str] = []
    zh_cn = _as_dict(content.get("zh_cn"))
    content_blocks = zh_cn.get("content")
    if isinstance(content_blocks, list):
        for block in content_blocks:
            if not isinstance(block, list):
                continue
            for item in block:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                if text:
                    lines.append(text)
    return "\n".join(lines)
