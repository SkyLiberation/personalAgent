from __future__ import annotations

from datetime import datetime, timedelta

from ..core.models import AgentState, Citation, KnowledgeNote, ReviewCard
from ..storage.memory_store import LocalMemoryStore


def capture_node(state: AgentState, store: LocalMemoryStore) -> AgentState:
    if state.raw_item is None:
        return state

    content = state.raw_item.content.strip()
    title = content[:24] + ("..." if len(content) > 24 else "")
    summary = content[:120]
    tags = _extract_tags(content)

    note = KnowledgeNote(
        user_id=state.raw_item.user_id,
        source_type=state.raw_item.source_type,
        source_ref=state.raw_item.source_ref,
        title=title or "Untitled note",
        content=content,
        summary=summary,
        tags=tags,
        updated_at=datetime.utcnow(),
    )
    state.note = note
    return state


def enrich_node(state: AgentState, store: LocalMemoryStore) -> AgentState:
    if state.note is None:
        return state

    state.note.summary = summarize_text(state.note.content)
    if not state.note.tags:
        state.note.tags = _extract_tags(state.note.content)
    return state


def link_node(state: AgentState, store: LocalMemoryStore) -> AgentState:
    if state.note is None:
        return state

    matches = store.find_similar_notes(state.note.user_id, state.note.content)
    state.matches = matches
    state.note.related_note_ids = [match.id for match in matches]
    store.add_note(state.note)
    return state


def schedule_review_node(state: AgentState, store: LocalMemoryStore) -> AgentState:
    if state.note is None:
        return state

    review = ReviewCard(
        note_id=state.note.id,
        prompt=f"请用一句话回忆：{state.note.summary}",
        answer_hint=state.note.summary,
        interval_days=1,
        due_at=datetime.utcnow() + timedelta(days=1),
    )
    state.review_card = review
    store.add_review(review)
    return state


def answer_node(state: AgentState, store: LocalMemoryStore) -> AgentState:
    if not state.question:
        return state

    matches = store.find_similar_notes(state.user_id, state.question)
    state.matches = matches
    if not matches:
        state.answer = "我暂时无法从你的个人知识库中找到足够依据来回答这个问题。"
        state.citations = []
        return state

    best = matches[0]
    state.answer = f"根据你已有的笔记，最相关的结论是：{best.summary}"
    state.citations = [
        Citation(note_id=note.id, title=note.title, snippet=note.summary[:80]) for note in matches
    ]
    return state


def digest_node(store: LocalMemoryStore, user_id: str) -> str:
    due = store.due_reviews(user_id)
    notes = store.list_notes(user_id)[-5:]
    lines = ["今日知识简报"]
    if notes:
        lines.append("最近新增笔记：")
        lines.extend(f"- {note.title}: {note.summary}" for note in notes)
    if due:
        lines.append("待复习内容：")
        lines.extend(f"- {review.prompt}" for review in due)
    if len(lines) == 1:
        lines.append("当前还没有知识记录。")
    return "\n".join(lines)


def summarize_text(text: str) -> str:
    text = text.strip().replace("\n", " ")
    if len(text) <= 120:
        return text
    return text[:117] + "..."


def _extract_tags(text: str) -> list[str]:
    candidates = [token.strip(" ,.;:!?()[]{}").lower() for token in text.split()]
    unique: list[str] = []
    for token in candidates:
        if len(token) < 3:
            continue
        if token not in unique:
            unique.append(token)
        if len(unique) == 5:
            break
    return unique
