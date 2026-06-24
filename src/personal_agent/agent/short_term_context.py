"""短期记忆（thread 对话）进 prompt 前的统一裁剪策略。

集中处理 token 预算、单条消息截断、滑动窗口与溢出滚动摘要，替代原先散落在
``_helpers.py`` / ``runtime_ask.py`` / ``query_planner.py`` 的硬编码常量。

设计为纯函数为主，不依赖 runtime/store，便于单元测试。两种入参形态：
- LangGraph ``BaseMessage``（带 ``.type`` ``human``/``ai``）
- dict 形态 ``ConversationMessage``（带 ``role`` ``user``/``assistant``）
"""

from __future__ import annotations

import logging
import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable

from pydantic import ValidationError

from ..core.config import ShortTermMemoryConfig
from ..core.models import ThreadSummary, local_now
from ..core.structured_parse import load_json_lenient

logger = logging.getLogger(__name__)

ConversationMessage = dict[str, str]

_TRUNCATION_MARK = "…[已截断]…"
_SUMMARY_ROLE = "user"
_SUMMARY_PREFIX = "[结构化短期摘要]"
_SUMMARY_BOUNDARY = (
    "边界：以下内容只用于理解指代、用户目标和已确认选择；"
    "不能替代 evidence、工具结果或长期知识。"
)


@dataclass
class WindowResult:
    """窗口裁剪结果。"""

    kept: list[ConversationMessage] = field(default_factory=list)
    overflow: list[ConversationMessage] = field(default_factory=list)
    total_considered: int = 0


@dataclass
class DialogueContextResult:
    """Final dialogue context plus the checkpointable structured summary."""

    messages: list[ConversationMessage] = field(default_factory=list)
    thread_summary: ThreadSummary | None = None
    summary_updated: bool = False
    window: WindowResult = field(default_factory=WindowResult)


@lru_cache(maxsize=8)
def _token_encoder(encoding_name: str) -> Any | None:
    try:
        import tiktoken  # type: ignore

        return tiktoken.get_encoding(encoding_name)
    except Exception:
        logger.debug("Tokenizer unavailable; using heuristic token estimate", exc_info=True)
        return None


def _heuristic_tokens(text: str, cfg: ShortTermMemoryConfig) -> int:
    cjk = sum(1 for ch in text if _is_cjk(ch))
    other = len(text) - cjk
    tokens = cjk / max(cfg.cjk_chars_per_token, 0.1) + other / max(
        cfg.latin_chars_per_token, 0.1
    )
    return max(1, int(tokens + 0.5))


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF      # CJK 统一表意
        or 0x3040 <= code <= 0x30FF   # 日文假名
        or 0xAC00 <= code <= 0xD7A3   # 韩文音节
        or 0x3400 <= code <= 0x4DBF   # CJK 扩展 A
    )


def estimate_tokens(text: str, cfg: ShortTermMemoryConfig) -> int:
    """Token estimate for prompt budgeting.

    Uses tiktoken when available/configured; otherwise falls back to the
    previous CJK/Latin heuristic so local tests and offline runs stay usable.
    """
    if not text:
        return 0
    if cfg.tokenizer_enabled:
        encoder = _token_encoder(cfg.tokenizer_encoding)
        if encoder is not None:
            try:
                return max(1, len(encoder.encode(text)))
            except Exception:
                logger.debug("Tokenizer encode failed; using heuristic", exc_info=True)
    return _heuristic_tokens(text, cfg)


def truncate_message_content(content: str, cfg: ShortTermMemoryConfig) -> str:
    """单条超长消息截断，保留首尾、中间插入截断标记。"""
    limit = cfg.per_message_char_limit
    if limit <= 0 or len(content) <= limit:
        return content
    keep = max(limit - len(_TRUNCATION_MARK), 1)
    head = keep * 2 // 3
    tail = keep - head
    if tail <= 0:
        return content[:head] + _TRUNCATION_MARK
    return content[:head] + _TRUNCATION_MARK + content[-tail:]


def _normalize(message: Any) -> ConversationMessage | None:
    """把 BaseMessage 或 dict 归一为 ``{"role", "content"}``，过滤非对话消息。"""
    role: str | None = None
    content: str = ""
    msg_type = getattr(message, "type", None)
    if msg_type is not None:  # LangGraph BaseMessage
        if msg_type == "human":
            role = "user"
        elif msg_type == "ai":
            role = "assistant"
        content = str(getattr(message, "content", ""))
    elif isinstance(message, dict):
        raw_role = message.get("role")
        if raw_role in {"user", "assistant"}:
            role = raw_role
        content = str(message.get("content", ""))
    if role is None:
        return None
    content = content.strip()
    if not content:
        return None
    return {"role": role, "content": content}


def apply_window(
    messages: list[Any],
    cfg: ShortTermMemoryConfig,
    *,
    exclude_latest: bool = False,
) -> WindowResult:
    """统一窗口裁剪：过滤 → 排除当前轮 → token 预算 + 条数双约束。

    从最近往前累加，受 ``token_budget`` 与 ``max_messages`` 双重约束；每条先经
    单条截断。返回保留消息 ``kept`` 与被裁掉的更早消息 ``overflow``（供滚动摘要）。
    """
    source = messages[:-1] if exclude_latest and messages else messages
    normalized = [m for m in (_normalize(x) for x in source) if m is not None]
    total = len(normalized)

    kept_reversed: list[ConversationMessage] = []
    used_tokens = 0
    cut_index = 0  # normalized 中第一条被保留消息的下标
    for idx in range(total - 1, -1, -1):
        if len(kept_reversed) >= cfg.max_messages:
            cut_index = idx + 1
            break
        truncated = truncate_message_content(normalized[idx]["content"], cfg)
        cost = estimate_tokens(truncated, cfg)
        if kept_reversed and used_tokens + cost > cfg.token_budget:
            cut_index = idx + 1
            break
        kept_reversed.append({"role": normalized[idx]["role"], "content": truncated})
        used_tokens += cost
    else:
        cut_index = 0

    kept = list(reversed(kept_reversed))
    overflow = normalized[:cut_index]
    return WindowResult(kept=kept, overflow=overflow, total_considered=total)


def render_as_text(messages: list[Any]) -> str:
    """统一渲染为 ``用户:`` / ``助手:`` 多行文本（替代旧 ``_conversation_messages_text``）。"""
    lines: list[str] = []
    for raw in messages:
        norm = _normalize(raw)
        if norm is None:
            continue
        label = "用户" if norm["role"] == "user" else "助手"
        lines.append(f"{label}: {norm['content']}")
    return "\n".join(lines)


def render_with_budget(
    messages: list[Any], cfg: ShortTermMemoryConfig
) -> str:
    """字符预算内的纯文本渲染（替代 planner 的 ``[:800]``）。"""
    text = render_as_text(messages)
    budget = cfg.char_budget
    if budget > 0 and len(text) > budget:
        return text[:budget]
    return text


def _clean_items(values: Any, *, limit: int = 12) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        candidates = [values]
    elif isinstance(values, list):
        candidates = values
    else:
        candidates = [values]
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        text = str(value).strip()
        if not text or text in seen:
            continue
        cleaned.append(text)
        seen.add(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def parse_thread_summary(value: Any) -> ThreadSummary | None:
    """Parse structured or legacy summary output into ``ThreadSummary``."""
    if value is None:
        return None
    if isinstance(value, ThreadSummary):
        return value
    if isinstance(value, dict):
        return ThreadSummary.model_validate(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = load_json_lenient(text)
    except (json.JSONDecodeError, ValueError):
        return ThreadSummary(context_notes=[text], updated_at=local_now())
    if isinstance(parsed, dict):
        try:
            return ThreadSummary.model_validate(parsed)
        except ValidationError:
            return ThreadSummary(context_notes=[text], updated_at=local_now())
    if isinstance(parsed, list):
        return ThreadSummary(context_notes=_clean_items(parsed), updated_at=local_now())
    return ThreadSummary(context_notes=[text], updated_at=local_now())


def render_thread_summary(summary: ThreadSummary | None) -> str:
    """Render structured summary with explicit factual boundaries."""
    if summary is None or summary.is_empty():
        return ""
    sections = [
        ("用户目标", summary.user_goals),
        ("用户约束", summary.user_constraints),
        ("已确认决策", summary.confirmed_decisions),
        ("待办状态", summary.pending_tasks),
        ("开放问题", summary.open_questions),
        ("助手假设（不可当事实）", summary.assistant_assumptions),
        ("未验证声明（使用前必须重新验证）", summary.unverified_claims),
        ("证据引用", summary.evidence_refs),
        ("其他上下文线索", summary.context_notes),
    ]
    lines = [_SUMMARY_PREFIX, _SUMMARY_BOUNDARY]
    for label, items in sections:
        cleaned = _clean_items(items)
        if not cleaned:
            continue
        lines.append(f"{label}:")
        lines.extend(f"- {item}" for item in cleaned)
    return "\n".join(lines)


def _summary_message(summary: ThreadSummary | None) -> ConversationMessage | None:
    rendered = render_thread_summary(summary)
    if not rendered:
        return None
    return {"role": _SUMMARY_ROLE, "content": rendered}


def _summary_for_compression(summary: ThreadSummary | None) -> str:
    rendered = render_thread_summary(summary)
    if not rendered:
        return ""
    return f"已有结构化摘要：\n{rendered}"


def build_dialogue_context_result(
    messages: list[Any],
    cfg: ShortTermMemoryConfig,
    *,
    exclude_latest: bool = False,
    prior_summary: ThreadSummary | dict[str, Any] | str | None = None,
    summarizer: Callable[[str], str | dict[str, Any] | ThreadSummary] | None = None,
) -> DialogueContextResult:
    """Build prompt dialogue and optionally update a structured thread summary."""
    window = apply_window(messages, cfg, exclude_latest=exclude_latest)
    existing_summary = parse_thread_summary(prior_summary)
    active_summary = existing_summary
    summary_updated = False

    should_summarize = (
        cfg.rolling_summary_enabled
        and window.overflow
        and summarizer is not None
        and window.total_considered >= cfg.rolling_summary_trigger
    )
    if should_summarize:
        overflow_parts = [
            part
            for part in (_summary_for_compression(existing_summary), render_as_text(window.overflow))
            if part
        ]
        try:
            generated = summarizer("\n\n".join(overflow_parts))
            parsed = parse_thread_summary(generated)
            if parsed is not None and not parsed.is_empty():
                active_summary = parsed
                summary_updated = True
        except Exception:
            logger.debug("Rolling summary failed; using prior summary or truncation", exc_info=True)

    summary_msg = _summary_message(active_summary) if cfg.rolling_summary_enabled else None
    output = [summary_msg, *window.kept] if summary_msg else window.kept
    return DialogueContextResult(
        messages=output,
        thread_summary=active_summary,
        summary_updated=summary_updated,
        window=window,
    )


def build_dialogue_context(
    messages: list[Any],
    cfg: ShortTermMemoryConfig,
    *,
    exclude_latest: bool = False,
    summarizer: Callable[[str], str | dict[str, Any] | ThreadSummary] | None = None,
) -> list[ConversationMessage]:
    """构造最终进 prompt 的对话上下文，溢出部分可选滚动摘要。

    ``summarizer`` 接受渲染后的溢出文本、返回摘要字符串；通常由
    由 graph context 的 ``compress_context`` capability 适配而来。摘要失败或未配置时静默降级为纯截断。
    """
    return build_dialogue_context_result(
        messages,
        cfg,
        exclude_latest=exclude_latest,
        summarizer=summarizer,
    ).messages

