from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..core.models import AgentState, EntryInput, EntryIntent

if TYPE_CHECKING:
    from ..capture import CaptureService
    from .router import RouterDecision
    from .service import AskResult, CaptureResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EntryNodeDeps:
    classify_intent: Callable[[EntryInput], "RouterDecision"]
    capture: Callable[..., "CaptureResult"]
    ask: Callable[..., "AskResult"]
    capture_service: "CaptureService | None" = None
    summarize_thread: Callable[[str, str], str] | None = None


def route_entry_intent_node(state: AgentState, deps: EntryNodeDeps) -> AgentState:
    if state.entry_input is None:
        state.intent = "unknown"
        state.intent_reason = "缺少入口输入。"
        return state
    decision = deps.classify_intent(state.entry_input)
    state.intent = decision.route
    state.intent_reason = decision.user_visible_message
    logger.debug(
        "Entry routed intent=%s confidence=%.2f risk=%s confirm=%s user=%s",
        decision.route, decision.confidence, decision.risk_level,
        decision.requires_confirmation, state.user_id,
    )
    return state


def capture_entry_branch_node(state: AgentState, deps: EntryNodeDeps) -> AgentState:
    entry_input = state.entry_input
    if entry_input is None:
        state.answer = "未收到可采集内容。"
        return state
    logger.debug("Executing capture branch intent=%s user=%s", state.intent, state.user_id)
    if state.intent == "capture_file":
        file_path = entry_input.metadata.get("file_path", "")
        if file_path:
            from pathlib import Path
            path = Path(file_path)
            if path.exists() and deps.capture_service is not None:
                original_filename = entry_input.metadata.get("original_filename", path.name)
                file_bytes = path.read_bytes()
                capture_text = deps.capture_service.capture_text_from_upload(
                    filename=original_filename,
                    content_type=None,
                    file_bytes=file_bytes,
                    source_type="file",
                )
                result = deps.capture(
                    text=capture_text,
                    source_type="file",
                    user_id=entry_input.user_id,
                    source_ref=entry_input.source_ref or file_path,
                )
                state.note = result.note
                state.matches = result.related_notes
                state.review_card = result.review_card
                state.answer = f"已收进知识库：{result.note.title}"
                return state
        state.answer = "文件消息已识别，但文件内容暂未获取到。请通过 Web 端上传文件，或稍后重试。"
        return state

    capture_text = entry_input.text
    source_type = "text"
    source_ref = entry_input.source_ref
    if state.intent == "capture_link":
        source_type = "link"
        url = entry_input.metadata.get("url") or first_url(entry_input.text)
        if not url:
            state.answer = "识别成了链接采集，但消息里没有找到可用链接。"
            return state
        source_ref = url
        if deps.capture_service is None:
            state.answer = "当前没有可用的采集服务，暂时无法抓取链接正文。"
            return state
        capture_text = deps.capture_service.capture_text_from_url(url)

    result = deps.capture(
        text=capture_text,
        source_type=source_type,
        user_id=entry_input.user_id,
        source_ref=source_ref,
    )
    state.note = result.note
    state.matches = result.related_notes
    state.review_card = result.review_card
    state.answer = f"已收进知识库：{result.note.title}"
    return state


def ask_entry_branch_node(state: AgentState, deps: EntryNodeDeps) -> AgentState:
    entry_input = state.entry_input
    if entry_input is None or not entry_input.text.strip():
        state.answer = "未收到可提问内容。"
        return state
    logger.debug("Executing ask branch user=%s question=%s", state.user_id, entry_input.text[:80])
    result = deps.ask(entry_input.text, entry_input.user_id, entry_input.session_id)
    state.question = entry_input.text
    state.answer = result.answer
    state.matches = result.matches
    state.citations = result.citations
    return state


def summarize_entry_branch_node(state: AgentState, deps: EntryNodeDeps | None = None) -> AgentState:
    entry_input = state.entry_input
    if entry_input is None:
        state.answer = "未收到可总结的内容。"
        return state
    logger.debug("Executing summarize branch user=%s", state.user_id)

    thread_messages_raw = entry_input.metadata.get("thread_messages", "")
    if thread_messages_raw and deps is not None and deps.summarize_thread is not None:
        try:
            messages = json.loads(thread_messages_raw)
            if isinstance(messages, list) and messages:
                messages_text = "\n".join(
                    f"[{m.get('role', 'unknown')}]: {m.get('content', '')}" for m in messages
                )
                summary = deps.summarize_thread(messages_text, entry_input.user_id or "default")
                state.answer = summary
                return state
        except (json.JSONDecodeError, Exception):
            pass

    chat_id = entry_input.metadata.get("chat_id", "")
    if chat_id:
        state.answer = (
            "已识别为群聊总结诉求。当前暂时无法获取会话消息，请稍后重试，"
            "或直接粘贴需要总结的聊天内容。"
        )
    else:
        state.answer = (
            "已识别为总结诉求。请直接发送需要总结的文本内容，"
            "或在群聊中使用此功能。"
        )
    return state


def unknown_entry_branch_node(state: AgentState) -> AgentState:
    logger.info("Unknown intent branch user=%s intent=%s", state.user_id, state.intent)
    state.answer = "我暂时没判断出你的意图。你可以直接发要记录的内容、要收录的链接，或明确提一个问题。"
    return state


def heuristic_entry_intent(text: str) -> tuple[EntryIntent, str]:
    stripped = text.strip()
    if not stripped:
        return "unknown", "消息内容为空。"

    url = first_url(stripped)
    summarize_keywords = ("总结", "汇总", "整理")
    thread_keywords = ("群聊", "会话", "线程", "讨论", "聊天记录")
    ask_keywords = ("什么", "为什么", "如何", "怎么", "吗", "？", "?", "请问", "帮我看看", "解释")
    capture_keywords = ("记一下", "记录", "收进", "保存", "沉淀", "备忘")
    delete_keywords = ("删除", "删掉", "移除", "去掉", "清除", "别再保留", "不要保留")
    knowledge_context = ("笔记", "知识", "记录", "那条", "这条", "那个", "结论", "卡片", "内容")
    solidify_keywords = ("记下来", "记录下来", "沉淀成", "固化成", "收录结论", "收进知识", "沉淀下来", "固化下来")

    if any(keyword in stripped for keyword in summarize_keywords) and any(
        keyword in stripped for keyword in thread_keywords
    ):
        return "summarize_thread", "文本里同时出现了总结和会话类关键词。"

    if any(keyword in stripped for keyword in delete_keywords) and any(
        keyword in stripped for keyword in knowledge_context
    ):
        return "delete_knowledge", "文本里包含删除意图和相关知识上下文。"

    if any(keyword in stripped for keyword in solidify_keywords):
        return "solidify_conversation", "文本里包含沉淀或固化对话结论的表达。"

    if url:
        if any(keyword in stripped for keyword in ask_keywords):
            return "ask", "消息里有链接，但整体更像围绕链接发起提问。"
        return "capture_link", "消息中包含链接，优先按链接采集处理。"
    if any(keyword in stripped for keyword in ask_keywords):
        return "ask", "文本里包含明显的问题表达。"
    if any(keyword in stripped for keyword in capture_keywords):
        return "capture_text", "文本里包含记录或沉淀类表达。"
    return "capture_text", "默认按文本采集处理。"


def first_url(text: str) -> str | None:
    match = re.search(r"https?://\S+", text)
    if match is None:
        return None
    return match.group(0).rstrip(".,);]}>\"'")
