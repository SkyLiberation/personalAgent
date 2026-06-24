from __future__ import annotations

import json
from collections.abc import Callable

from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from personal_agent.feishu.models import FeishuIncomingMessage


def parse_p2_message_event(
    data: P2ImMessageReceiveV1,
    *,
    resolve_user_id: Callable[[str, str], str],
) -> FeishuIncomingMessage | None:
    event = data.event
    if event is None or event.message is None:
        return None

    message = event.message
    sender = event.sender
    sender_id = sender.sender_id if sender is not None else None
    header = data.header
    content = safe_json_loads(message.content or "{}")
    metadata: dict[str, str] = {}

    if message.message_type == "text":
        text = str(content.get("text") or "").strip()
    elif message.message_type == "file":
        metadata["file_key"] = str(content.get("file_key") or "")
        text = str(content.get("file_name") or "飞书文件").strip()
    elif message.message_type == "post":
        text = extract_post_text(content)
    else:
        text = str(content.get("text") or message.message_type or "").strip()

    chat_id = str(message.chat_id or "")
    open_id = str(sender_id.open_id or "") if sender_id is not None else ""
    sender_user_id = str(sender_id.user_id or "") if sender_id is not None else ""
    user_id = resolve_user_id(open_id, sender_user_id)
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


def safe_json_loads(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def extract_post_text(content: dict[str, object]) -> str:
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


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}
