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

from personal_agent.adapters.feishu.message_parser import parse_p2_message_event, safe_json_loads
from personal_agent.adapters.feishu.models import FeishuIncomingMessage

logger = logging.getLogger(__name__)


class FeishuClientMixin:
    def start_event_listener(self) -> None:
        if not self.settings.feishu.enabled:
            logger.info("Skip Feishu long connection because integration is disabled")
            return
        if not (self.settings.feishu.app_id and self.settings.feishu.app_secret):
            logger.info("Skip Feishu long connection because app credentials are not configured")
            return

        with self._ws_lock:
            if self._ws_started:
                logger.info("Feishu long connection already started")
                return

            self._ws_client = lark.ws.Client(
                self.settings.feishu.app_id,
                self.settings.feishu.app_secret,
                event_handler=self._event_handler(),
                log_level=lark.LogLevel.INFO,
                domain=self.settings.feishu.base_url.rstrip("/"),
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
        return parse_p2_message_event(data, resolve_user_id=self._resolve_user_id)

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

    def _reply_to_message(self, incoming_message: FeishuIncomingMessage, reply_text: str) -> None:
        if not (self.settings.feishu.app_id and self.settings.feishu.app_secret):
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

    def send_text_to_chat(self, chat_id: str, text: str) -> None:
        """Send a proactive text message to a Feishu chat."""
        if not (self.settings.feishu.app_id and self.settings.feishu.app_secret):
            logger.info("Skip Feishu proactive send because app credentials are not configured chat_id=%s", chat_id)
            return
        self._create_chat_message(chat_id=chat_id, text=text)

    def send_digest(self, chat_id: str, digest_text: str) -> None:
        """Send a review digest to a Feishu chat."""
        self.send_text_to_chat(chat_id, digest_text)

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
        self._create_chat_message(
            chat_id=chat_id,
            text=reply_text,
            event_id=incoming_message.event_id,
            message_id=incoming_message.message_id,
        )
        logger.info(
            "Feishu reply sent event_id=%s message_id=%s chat_id=%s mode=create",
            incoming_message.event_id,
            incoming_message.message_id,
            chat_id,
        )

    def _create_chat_message(
        self,
        *,
        chat_id: str,
        text: str,
        event_id: str | None = None,
        message_id: str | None = None,
    ) -> None:
        request = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .msg_type("text")
                .build()
            ) \
            .build()

        response = self._client_value().im.v1.message.create(request)
        self._ensure_success(
            response=response,
            action="create message",
            event_id=event_id,
            message_id=message_id,
            chat_id=chat_id,
        )
        logger.info("Feishu proactive message sent chat_id=%s", chat_id)

    def _client_value(self) -> lark.Client:
        if self._client is None:
            self._client = lark.Client.builder() \
                .app_id(self.settings.feishu.app_id or "") \
                .app_secret(self.settings.feishu.app_secret or "") \
                .domain(self.settings.feishu.base_url.rstrip("/")) \
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
        if not (self.settings.feishu.app_id and self.settings.feishu.app_secret):
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
        if not (self.settings.feishu.app_id and self.settings.feishu.app_secret):
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
                    content = safe_json_loads(item.body.content if item.body else "{}")
                    text = str(content.get("text") or "").strip()
                    if text:
                        role = "user" if item.sender.id != "bot" else "assistant"
                        messages.append({"role": role, "content": text})
            return messages
        except Exception:
            logger.exception("Feishu message fetch exception chat_id=%s", chat_id)
            return []

    def _resolve_user_id(self, open_id: str, sender_user_id: str) -> str:
        if self.settings.feishu.use_default_user:
            return self.settings.default_user
        return open_id or sender_user_id or self.settings.default_user
