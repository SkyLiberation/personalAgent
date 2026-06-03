"""短期记忆上下文管理策略单元测试。"""

from __future__ import annotations

from personal_agent.core.config import ShortTermMemoryConfig
from personal_agent.agent.short_term_context import (
    apply_window,
    build_dialogue_context,
    estimate_tokens,
    render_as_text,
    render_with_budget,
    truncate_message_content,
)


def _cfg(**overrides) -> ShortTermMemoryConfig:
    return ShortTermMemoryConfig(**overrides)


def _msg(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


class _FakeBaseMessage:
    """模拟 LangGraph BaseMessage（带 .type/.content）。"""

    def __init__(self, msg_type: str, content: str) -> None:
        self.type = msg_type
        self.content = content


def test_estimate_tokens_cjk_vs_latin():
    cfg = _cfg()
    # 中文按 1.5 字/token：6 字 ≈ 4 token
    assert estimate_tokens("你好世界一二", cfg) == 4
    # 英文按 4 字/token：8 字 ≈ 2 token
    assert estimate_tokens("abcdefgh", cfg) == 2
    # 混合大于任一纯量
    assert estimate_tokens("你好abcd", cfg) >= estimate_tokens("abcd", cfg)
    assert estimate_tokens("", cfg) == 0


def test_truncate_message_content_long_and_short():
    cfg = _cfg(per_message_char_limit=20)
    short = "短消息"
    assert truncate_message_content(short, cfg) == short

    long = "A" * 100
    out = truncate_message_content(long, cfg)
    assert len(out) <= 20 + len("…[已截断]…")
    assert "…[已截断]…" in out
    assert out.startswith("A")
    assert out.endswith("A")


def test_apply_window_respects_max_messages():
    cfg = _cfg(max_messages=2, token_budget=10_000)
    msgs = [_msg("user", f"m{i}") for i in range(5)]
    result = apply_window(msgs, cfg)
    assert len(result.kept) == 2
    assert result.kept[-1]["content"] == "m4"
    assert len(result.overflow) == 3
    assert result.total_considered == 5


def test_apply_window_token_budget_overrides_count():
    # 预算极小，只能放下最后一条
    cfg = _cfg(max_messages=10, token_budget=1, per_message_char_limit=10_000)
    msgs = [_msg("user", "x" * 40) for _ in range(4)]
    result = apply_window(msgs, cfg)
    assert len(result.kept) == 1  # 至少保留最近一条
    assert len(result.overflow) == 3


def test_apply_window_exclude_latest_and_role_filter():
    cfg = _cfg(max_messages=10, token_budget=10_000)
    msgs = [
        _msg("user", "u1"),
        _msg("assistant", "a1"),
        {"role": "system", "content": "ignore me"},
        _msg("user", "current"),
    ]
    result = apply_window(msgs, cfg, exclude_latest=True)
    contents = [m["content"] for m in result.kept]
    assert "current" not in contents  # 当前轮被排除
    assert "ignore me" not in contents  # system 被过滤
    assert contents == ["u1", "a1"]


def test_apply_window_accepts_base_messages():
    cfg = _cfg(max_messages=10, token_budget=10_000)
    msgs = [
        _FakeBaseMessage("human", "hi"),
        _FakeBaseMessage("ai", "hello"),
        _FakeBaseMessage("tool", "tool-output"),
    ]
    result = apply_window(msgs, cfg)
    assert [m["role"] for m in result.kept] == ["user", "assistant"]
    assert [m["content"] for m in result.kept] == ["hi", "hello"]


def test_render_as_text_and_budget():
    msgs = [_msg("user", "问题"), _msg("assistant", "回答")]
    text = render_as_text(msgs)
    assert text == "用户: 问题\n助手: 回答"

    cfg = _cfg(char_budget=5)
    assert len(render_with_budget(msgs, cfg)) == 5


def test_build_dialogue_context_no_summary_when_disabled():
    cfg = _cfg(max_messages=2, token_budget=10_000, rolling_summary_enabled=False)
    msgs = [_msg("user", f"m{i}") for i in range(5)]
    out = build_dialogue_context(msgs, cfg, summarizer=lambda _t: "SUMMARY")
    assert [m["content"] for m in out] == ["m3", "m4"]


def test_build_dialogue_context_injects_summary_on_overflow():
    cfg = _cfg(
        max_messages=2,
        token_budget=10_000,
        rolling_summary_enabled=True,
        rolling_summary_trigger=3,
    )
    msgs = [_msg("user", f"m{i}") for i in range(5)]
    captured = {}

    def summarizer(text: str) -> str:
        captured["text"] = text
        return "早前要点"

    out = build_dialogue_context(msgs, cfg, summarizer=summarizer)
    assert out[0]["content"].startswith("[早前对话摘要]")
    assert "早前要点" in out[0]["content"]
    assert [m["content"] for m in out[1:]] == ["m3", "m4"]
    assert "m0" in captured["text"]  # 溢出内容确实喂给了 summarizer


def test_build_dialogue_context_falls_back_on_summarizer_error():
    cfg = _cfg(
        max_messages=2,
        token_budget=10_000,
        rolling_summary_enabled=True,
        rolling_summary_trigger=3,
    )
    msgs = [_msg("user", f"m{i}") for i in range(5)]

    def boom(_text: str) -> str:
        raise RuntimeError("LLM down")

    out = build_dialogue_context(msgs, cfg, summarizer=boom)
    # 降级为纯截断，不抛异常、不注入摘要
    assert [m["content"] for m in out] == ["m3", "m4"]


def test_build_dialogue_context_no_summary_below_trigger():
    cfg = _cfg(
        max_messages=2,
        token_budget=10_000,
        rolling_summary_enabled=True,
        rolling_summary_trigger=99,
    )
    msgs = [_msg("user", f"m{i}") for i in range(5)]
    out = build_dialogue_context(msgs, cfg, summarizer=lambda _t: "SUMMARY")
    assert all("[早前对话摘要]" not in m["content"] for m in out)
