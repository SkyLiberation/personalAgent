"""Ask quality evaluation test cases.

Each case describes a scenario with questions, expected matched notes, and
the minimum evidence score that a good answer should achieve.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from personal_agent.core.models import Citation, KnowledgeNote


@dataclass
class AskEvalCase:
    id: str
    description: str
    question: str
    notes: list[KnowledgeNote]
    citations: list[Citation]
    # Minimum acceptable evidence score
    min_score: float = 0.4
    # Answer must not contain these phrases
    forbidden_phrases: list[str] = field(default_factory=list)
    # Answer should contain at least one of these keywords
    expected_keywords: list[str] = field(default_factory=list)


def _note(note_id: str, title: str, content: str, summary: str = "") -> KnowledgeNote:
    return KnowledgeNote(
        id=note_id,
        title=title,
        content=content,
        summary=summary or title,
    )


def _citation(
    note_id: str,
    title: str,
    snippet: str = "...",
    relation_fact: str | None = None,
) -> Citation:
    return Citation(note_id=note_id, title=title, snippet=snippet, relation_fact=relation_fact)


# -- Well-supported ask cases ------------------------------------------------

WELL_SUPPORTED = [
    AskEvalCase(
        id="ask-001",
        description="单笔记完美匹配 — 答案应高分",
        question="什么是服务降级？",
        notes=[
            _note("n1", "服务降级", "服务降级是在系统压力过大时，主动关闭非核心功能以保障核心链路可用性的策略。"),
        ],
        citations=[_citation("n1", "服务降级")],
        min_score=0.25,
        expected_keywords=["服务降级"],
        forbidden_phrases=["我暂时无法", "暂无相关信息"],
    ),
    AskEvalCase(
        id="ask-002",
        description="多笔记匹配 — 答案应引用多个来源",
        question="Python有哪些测试框架？",
        notes=[
            _note("n1", "pytest入门", "pytest是Python最流行的测试框架，支持fixture和参数化。"),
            _note("n2", "unittest基础", "unittest是Python标准库自带的测试框架。"),
            _note("n3", "nose2简介", "nose2是unittest的扩展，提供更灵活的测试发现。"),
        ],
        citations=[
            _citation("n1", "pytest入门"),
            _citation("n2", "unittest基础"),
            _citation("n3", "nose2简介"),
        ],
        min_score=0.5,
        expected_keywords=["pytest", "unittest"],
        forbidden_phrases=["我暂时无法"],
    ),
    AskEvalCase(
        id="ask-003",
        description="图谱增强问答 — 应有额外加分",
        question="LangGraph的核心概念是什么？",
        notes=[
            _note("n1", "LangGraph StateGraph", "StateGraph是LangGraph的核心编排抽象。"),
            _note("n2", "LangGraph节点", "节点是StateGraph中的处理单元。"),
        ],
        citations=[
            _citation("n1", "LangGraph StateGraph"),
            _citation("n2", "LangGraph节点"),
        ],
        min_score=0.3,
        expected_keywords=["StateGraph", "节点"],
        forbidden_phrases=["我暂时无法"],
    ),
]

# -- Degraded answer cases ---------------------------------------------------

DEGRADED = [
    AskEvalCase(
        id="ask-004",
        description="孤儿引用 — 应触发 citation_valid=False",
        question="什么是Docker？",
        notes=[_note("n1", "无关笔记", "关于Python的笔记。")],
        citations=[_citation("n99", "Docker入门")],
        min_score=0.0,
        forbidden_phrases=[],
    ),
    AskEvalCase(
        id="ask-005",
        description="无匹配笔记 — 应给出低分",
        question="一个非常冷门的问题",
        notes=[],
        citations=[],
        min_score=0.0,
        expected_keywords=[],
    ),
    AskEvalCase(
        id="ask-006",
        description="空回答 — 必须零分",
        question="任何问题",
        notes=[_note("n1", "相关笔记", "相关内容")],
        citations=[_citation("n1", "相关笔记")],
        min_score=0.0,
    ),
]

ALL_ASK_CASES = WELL_SUPPORTED + DEGRADED
