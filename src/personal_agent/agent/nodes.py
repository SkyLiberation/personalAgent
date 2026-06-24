from __future__ import annotations

import logging
from datetime import timedelta

from personal_agent.kernel.models import (
    AgentState,
    Citation,
    ChunkDraft,
    KnowledgeNote,
    NoteBody,
    NoteChunk,
    NotePreExtract,
    NoteSource,
    ReviewCard,
    local_now,
)
from personal_agent.memory import MemoryFacade

logger = logging.getLogger(__name__)


def capture_node(state: AgentState, store: MemoryFacade) -> AgentState:
    if state.raw_item is None:
        return state

    content = state.raw_item.content.strip()
    metadata = dict(state.raw_item.metadata or {})
    title_source = metadata.get("title") or metadata.get("original_filename") or metadata.get("filename") or content
    title = title_source[:80] + ("..." if len(title_source) > 80 else "")
    summary = content[:120]
    tags = _extract_tags(content)

    from personal_agent.agent.provenance import HeuristicProvenanceExtractor

    provenance = HeuristicProvenanceExtractor().extract(state.raw_item)

    state.note = KnowledgeNote(
        user_id=state.raw_item.user_id,
        source=NoteSource(
            type=state.raw_item.source_type,
            ref=state.raw_item.source_ref,
            fingerprint=state.raw_item.source_fingerprint,
            provenance=provenance,
            metadata=metadata,
        ),
        body=NoteBody(title=title or "Untitled note", content=content, summary=summary),
        tags=tags,
        updated_at=local_now(),
    )
    state.chunk_drafts = []
    state.chunk_notes = []
    return state


def structural_chunk_node(state: AgentState, store: MemoryFacade) -> AgentState:
    """Create Unstructured-backed chunk drafts without committing final notes."""
    if state.note is None or state.raw_item is None:
        return state

    from personal_agent.core.document_partition import partition_to_chunk_drafts

    drafts = partition_to_chunk_drafts(
        state.note.body.content,
        source_type=state.raw_item.source_type,
        source_ref=state.raw_item.source_ref,
        metadata=state.raw_item.metadata,
    )
    if len(drafts) <= 1:
        state.chunk_drafts = []
        if drafts:
            state.note.source.metadata = {
                **dict(state.note.source.metadata),
                "unstructured": drafts[0].metadata,
            }
        return state

    state.note.chunk.index = 0
    state.chunk_drafts = drafts
    state.note.source.metadata = {
        **dict(state.note.source.metadata),
        "chunking": {
            "provider": "unstructured",
            "chunk_count": len(drafts),
        },
    }
    return state


def chunk_reconcile_node(state: AgentState, store: MemoryFacade) -> AgentState:
    """Build final chunk notes from Unstructured chunk drafts."""
    if state.note is None or state.raw_item is None:
        return state

    state.chunk_notes = _chunk_notes_from_drafts(
        state.note,
        state.raw_item,
        state.chunk_drafts,
    )
    if state.chunk_notes:
        state.note.chunk.index = 0
    return state


def _chunk_notes_from_drafts(
    parent: KnowledgeNote,
    raw_item,
    drafts: list[ChunkDraft],
) -> list[KnowledgeNote]:
    from personal_agent.agent.chunk_quality import score_drafts

    chunks: list[KnowledgeNote] = []
    scored = score_drafts(drafts)
    for i, (draft, quality_score, retrievable) in enumerate(scored, 1):
        metadata = {
            **dict(raw_item.metadata or {}),
            "chunking": {
                "provider": "unstructured",
                "category": draft.category,
                "title_path": draft.title_path,
                "element_ids": draft.element_ids,
                "page_number": draft.page_number,
                "metadata": draft.metadata,
            },
        }
        chunks.append(
            KnowledgeNote(
                user_id=raw_item.user_id,
                source=NoteSource(
                    type=raw_item.source_type,
                    ref=raw_item.source_ref,
                    fingerprint=raw_item.source_fingerprint,
                    provenance=parent.source.provenance,
                    metadata=metadata,
                ),
                body=NoteBody(
                    title=draft.title,
                    content=draft.content,
                    summary=draft.content[:120].replace("\n", " "),
                ),
                tags=_extract_tags(draft.content),
                chunk=NoteChunk(
                    parent_note_id=parent.id,
                    index=i,
                    source_span=draft.source_span,
                    title_path=list(draft.title_path),
                    page_number=draft.page_number,
                    element_ids=list(draft.element_ids),
                    coordinates=draft.coordinates,
                    retrievable=retrievable,
                    quality_score=round(quality_score, 4),
                ),
                preextract=NotePreExtract(
                    graph_worthy=None,
                    status="skipped",
                    topic=" > ".join(draft.title_path) if draft.title_path else None,
                ),
                updated_at=local_now(),
            )
        )
    return chunks


def enrich_node(state: AgentState, store: MemoryFacade) -> AgentState:
    if state.note is None:
        return state

    state.note.body.summary = summarize_text(state.note.body.content)
    if not state.note.tags:
        state.note.tags = _extract_tags(state.note.body.content)
    return state


def link_node(state: AgentState, store: MemoryFacade) -> AgentState:
    if state.note is None:
        return state

    matches = store.find_similar_notes(state.note.user_id, state.note.body.content)
    state.matches = matches
    state.note.related_note_ids = [match.id for match in matches]
    store.add_note(state.note)
    for chunk in state.chunk_notes:
        store.add_note(chunk)
    return state


def schedule_review_node(state: AgentState, store: MemoryFacade) -> AgentState:
    if state.note is None:
        return state

    review = ReviewCard(
        note_id=state.note.id,
        prompt=f"请用一句话回忆：{state.note.body.summary}",
        answer_hint=state.note.body.summary,
        interval_days=1,
        due_at=local_now() + timedelta(days=1),
    )
    state.review_card = review
    store.add_review(review)
    return state


def answer_node(state: AgentState, store: MemoryFacade) -> AgentState:
    if not state.question:
        return state

    matches = store.find_similar_notes(state.user_id, state.question)
    state.matches = matches
    if not matches:
        state.answer = "我暂时无法从你的个人知识库中找到足够依据来回答这个问题。"
        state.citations = []
        return state

    best = matches[0]
    state.answer = f"根据你已有的笔记，最相关的结论是：{best.body.summary}"
    state.citations = [
        Citation(note_id=note.id, title=note.body.title, snippet=note.body.summary[:80]) for note in matches
    ]
    return state


def digest_node(store: MemoryFacade, user_id: str) -> str:
    due = store.due_reviews(user_id)
    notes = store.list_notes(user_id)[-5:]
    lines = ["今日知识简报"]
    if notes:
        lines.append("最近新增笔记：")
        lines.extend(f"- {note.body.title}: {note.body.summary}" for note in notes)
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
