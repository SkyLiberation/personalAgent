"""短期记忆上下文管理策略单元测试。"""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

from personal_agent.orchestration.orchestration_models import AgentGraphState
from personal_agent.orchestration.orchestration_nodes._entry import _entry_conversation_messages
from personal_agent.kernel.config import ShortTermMemoryConfig
from personal_agent.memory.short_term_context import (
    apply_window,
    build_dialogue_context,
    build_dialogue_context_result,
    estimate_tokens,
    parse_thread_summary,
    render_as_text,
    render_thread_summary,
    render_with_budget,
    truncate_message_content,
)
from personal_agent.kernel.models import ThreadSummary


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
    cfg = _cfg(tokenizer_enabled=False)
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
    assert out[0]["content"].startswith("[结构化短期摘要]")
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
    assert all("[结构化短期摘要]" not in m["content"] for m in out)


def test_parse_and_render_thread_summary_json_keeps_boundaries():
    summary = parse_thread_summary(
        """
        {
          "user_goals": ["继续优化 memory P1"],
          "confirmed_decisions": ["不考虑兼容性"],
          "assistant_assumptions": ["可能需要改 short_term_context"],
          "unverified_claims": ["某个外部库一定可用"],
          "evidence_refs": ["note-1"]
        }
        """
    )

    rendered = render_thread_summary(summary)

    assert isinstance(summary, ThreadSummary)
    assert "用户目标" in rendered
    assert "助手假设（不可当事实）" in rendered
    assert "未验证声明（使用前必须重新验证）" in rendered
    assert "不能替代 evidence" in rendered


def test_parse_thread_summary_accepts_fenced_json():
    summary = parse_thread_summary(
        '```json\n{"user_constraints": ["回答要简洁"]}\n```'
    )

    assert summary is not None
    assert summary.user_constraints == ["回答要简洁"]


def test_build_dialogue_context_result_updates_structured_summary():
    cfg = _cfg(
        max_messages=1,
        token_budget=10_000,
        rolling_summary_enabled=True,
        rolling_summary_trigger=2,
    )
    msgs = [_msg("user", "目标：优化短期摘要"), _msg("assistant", "我会处理"), _msg("user", "继续")]
    captured = {}

    def summarizer(text: str) -> str:
        captured["text"] = text
        return '{"user_goals": ["优化短期摘要"], "pending_tasks": ["继续执行 P1"]}'

    result = build_dialogue_context_result(msgs, cfg, summarizer=summarizer)

    assert result.summary_updated is True
    assert result.thread_summary is not None
    assert result.thread_summary.user_goals == ["优化短期摘要"]
    assert result.messages[0]["content"].startswith("[结构化短期摘要]")
    assert result.messages[-1]["content"] == "继续"
    assert "目标：优化短期摘要" in captured["text"]


def test_build_dialogue_context_result_reuses_prior_summary_when_no_overflow():
    cfg = _cfg(max_messages=10, token_budget=10_000, rolling_summary_enabled=True)
    prior = ThreadSummary(user_goals=["回答当前追问"])
    msgs = [_msg("user", "现在怎么做？")]

    result = build_dialogue_context_result(msgs, cfg, prior_summary=prior)

    assert result.summary_updated is False
    assert result.messages[0]["content"].startswith("[结构化短期摘要]")
    assert "回答当前追问" in result.messages[0]["content"]
    assert result.messages[1]["content"] == "现在怎么做？"


def test_entry_conversation_messages_persist_thread_summary():
    state = AgentGraphState(
        user_id="u1",
        messages=[
            HumanMessage(content="目标：升级短期摘要"),
            AIMessage(content="我会先检查实现"),
            HumanMessage(content="继续"),
        ],
    )
    deps = SimpleNamespace(
        settings=SimpleNamespace(
            short_term=_cfg(
                max_messages=1,
                token_budget=10_000,
                rolling_summary_enabled=True,
                rolling_summary_trigger=2,
            )
        ),
        compress_context=lambda text, _user_id: (
            '{"user_goals": ["升级短期摘要"], "confirmed_decisions": ["不考虑兼容性"]}'
        ),
    )

    messages = _entry_conversation_messages(state, exclude_latest=False, deps=deps)

    assert state.thread_summary is not None
    assert state.thread_summary.user_goals == ["升级短期摘要"]
    assert messages[0]["content"].startswith("[结构化短期摘要]")
    assert messages[-1]["content"] == "继续"
