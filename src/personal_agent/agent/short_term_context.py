"""短期记忆（thread 对话）进 prompt 前的统一裁剪策略。

集中处理 token 预算、单条消息截断、滑动窗口与溢出滚动摘要，替代原先散落在
``_helpers.py`` / ``runtime_ask.py`` / ``query_planner.py`` 的硬编码常量。

设计为纯函数为主，不依赖 runtime/store，便于单元测试。两种入参形态：
- LangGraph ``BaseMessage``（带 ``.type`` ``human``/``ai``）
- dict 形态 ``ConversationMessage``（带 ``role`` ``user``/``assistant``）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.config import ShortTermMemoryConfig

logger = logging.getLogger(__name__)

ConversationMessage = dict[str, str]

_TRUNCATION_MARK = "…[已截断]…"
_SUMMARY_ROLE = "user"
_SUMMARY_PREFIX = "[早前对话摘要]"


@dataclass
class WindowResult:
    """窗口裁剪结果。"""

    kept: list[ConversationMessage] = field(default_factory=list)
    overflow: list[ConversationMessage] = field(default_factory=list)
    total_considered: int = 0


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF      # CJK 统一表意
        or 0x3040 <= code <= 0x30FF   # 日文假名
        or 0xAC00 <= code <= 0xD7A3   # 韩文音节
        or 0x3400 <= code <= 0x4DBF   # CJK 扩展 A
    )


def estimate_tokens(text: str, cfg: ShortTermMemoryConfig) -> int:
    """字符启发式 token 估算：CJK 与拉丁字符分别按不同折算率求和。

    中文模型的精确分词器本就不通用，这里用足够做预算控制的近似：
    CJK ≈ ``cjk_chars_per_token`` 字/token，其余 ≈ ``latin_chars_per_token`` 字/token。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if _is_cjk(ch))
    other = len(text) - cjk
    tokens = cjk / max(cfg.cjk_chars_per_token, 0.1) + other / max(
        cfg.latin_chars_per_token, 0.1
    )
    return max(1, int(tokens + 0.5))


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


def build_dialogue_context(
    messages: list[Any],
    cfg: ShortTermMemoryConfig,
    *,
    exclude_latest: bool = False,
    summarizer: Callable[[str], str] | None = None,
) -> list[ConversationMessage]:
    """构造最终进 prompt 的对话上下文，溢出部分可选滚动摘要。

    ``summarizer`` 接受渲染后的溢出文本、返回摘要字符串；通常由
    ``OrchestrationDeps.compress_context`` 适配而来。摘要失败或未配置时静默降级为纯截断。
    """
    window = apply_window(messages, cfg, exclude_latest=exclude_latest)
    if not (
        cfg.rolling_summary_enabled
        and window.overflow
        and summarizer is not None
        and window.total_considered >= cfg.rolling_summary_trigger
    ):
        return window.kept

    overflow_text = render_as_text(window.overflow)
    try:
        summary = summarizer(overflow_text)
    except Exception:
        logger.debug("Rolling summary failed; falling back to truncation", exc_info=True)
        return window.kept
    if not summary or not summary.strip():
        return window.kept

    summary_msg: ConversationMessage = {
        "role": _SUMMARY_ROLE,
        "content": f"{_SUMMARY_PREFIX}\n{summary.strip()}",
    }
    return [summary_msg, *window.kept]

