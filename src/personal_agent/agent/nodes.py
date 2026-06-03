from __future__ import annotations

import logging
from datetime import timedelta

from ..core.models import (
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
from ..extract import PreExtractService
from ..extract.schemas import SectionMap
from ..extract.schemas import SectionRecord
from ..storage.postgres_memory_store import PostgresMemoryStore

logger = logging.getLogger(__name__)


def capture_node(state: AgentState, store: PostgresMemoryStore) -> AgentState:
    if state.raw_item is None:
        return state

    content = state.raw_item.content.strip()
    metadata = dict(state.raw_item.metadata or {})
    title_source = metadata.get("title") or metadata.get("original_filename") or metadata.get("filename") or content
    title = title_source[:80] + ("..." if len(title_source) > 80 else "")
    summary = content[:120]
    tags = _extract_tags(content)

    state.note = KnowledgeNote(
        user_id=state.raw_item.user_id,
        source=NoteSource(
            type=state.raw_item.source_type,
            ref=state.raw_item.source_ref,
            fingerprint=state.raw_item.source_fingerprint,
            metadata=metadata,
        ),
        body=NoteBody(title=title or "Untitled note", content=content, summary=summary),
        tags=tags,
        updated_at=local_now(),
    )
    state.chunk_drafts = []
    state.chunk_notes = []
    return state


def structural_chunk_node(state: AgentState, store: PostgresMemoryStore) -> AgentState:
    """Create deterministic chunk drafts without committing final chunk notes."""
    if state.note is None or state.raw_item is None:
        return state

    from ..core.chunking import chunk_content

    chunks = chunk_content(state.note.body.content, state.raw_item.source_type)
    if len(chunks) <= 1:
        state.chunk_drafts = []
        return state

    state.note.chunk.index = 0
    state.chunk_drafts = [
        ChunkDraft(
            title=ch["title"],
            content=ch["content"],
            source_span=ch["source_span"],
        )
        for ch in chunks
    ]
    return state


def preextract_node(
    state: AgentState,
    store: PostgresMemoryStore,
    service: PreExtractService,
) -> AgentState:
    """Run lightweight LangExtract pre-extraction.

    Records section_map / preextract_status on the parent note. This node does
    not create or replace chunk notes; chunk materialization is handled by
    chunk_reconcile_node.
    """
    if state.note is None or state.raw_item is None:
        return state

    if not service.should_run(state.note.body.content):
        state.note.preextract.status = "skipped"
        return state

    try:
        section_map = service.extract(state.note.body.content)
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.warning("preextract_node failed user=%s err=%s", state.note.user_id, exc)
        state.note.preextract.status = "failed"
        return state

    state.note.preextract.section_map = section_map.model_dump(mode="json") if section_map.sections else None
    state.note.preextract.status = "ok" if section_map.sections else "skipped"
    if section_map.doc_topic:
        state.note.preextract.topic = section_map.doc_topic
    if section_map.sections:
        # Mark parent with aggregate graph_worthy: True if any section is worthy.
        state.note.preextract.graph_worthy = any(s.graph_worthy for s in section_map.sections)

    return state


def chunk_reconcile_node(state: AgentState, store: PostgresMemoryStore) -> AgentState:
    """Build final chunk notes from semantic sections or structural drafts."""
    if state.note is None or state.raw_item is None:
        return state

    section_map = (
        SectionMap.model_validate(state.note.preextract.section_map)
        if state.note.preextract.section_map
        else SectionMap()
    )
    if len(section_map.sections) >= 2:
        state.note.chunk.index = 0
        state.chunk_notes = _chunk_notes_from_sections(
            state.note,
            state.raw_item,
            section_map.sections,
        )
        return state

    state.chunk_notes = _chunk_notes_from_drafts(
        state.note,
        state.raw_item,
        state.chunk_drafts,
        graph_worthy=state.note.preextract.graph_worthy,
    )
    if state.chunk_notes:
        state.note.chunk.index = 0
    return state


def _chunk_notes_from_drafts(
    parent: KnowledgeNote,
    raw_item,
    drafts: list[ChunkDraft],
    *,
    graph_worthy: bool | None,
) -> list[KnowledgeNote]:
    chunks: list[KnowledgeNote] = []
    for i, draft in enumerate(drafts, 1):
        chunks.append(
            KnowledgeNote(
                user_id=raw_item.user_id,
                source=NoteSource(
                    type=raw_item.source_type,
                    ref=raw_item.source_ref,
                    fingerprint=raw_item.source_fingerprint,
                    metadata=dict(raw_item.metadata or {}),
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
                ),
                preextract=NotePreExtract(
                    graph_worthy=graph_worthy,
                    status=parent.preextract.status,
                    topic=parent.preextract.topic,
                ),
                updated_at=local_now(),
            )
        )
    return chunks


def _chunk_notes_from_sections(
    parent: KnowledgeNote,
    raw_item,
    sections: list[SectionRecord],
) -> list[KnowledgeNote]:
    chunks: list[KnowledgeNote] = []
    full_text = parent.body.content
    for i, section in enumerate(sections, 1):
        start = max(0, section.char_start)
        end = section.char_end if section.char_end > start else len(full_text)
        body = full_text[start:end].strip() or full_text[:120]
        title = section.topic or section.title or f"Section {i}"
        chunks.append(
            KnowledgeNote(
                user_id=raw_item.user_id,
                source=NoteSource(
                    type=raw_item.source_type,
                    ref=raw_item.source_ref,
                    fingerprint=raw_item.source_fingerprint,
                    metadata=dict(raw_item.metadata or {}),
                ),
                body=NoteBody(
                    title=title[:80],
                    content=body,
                    summary=(section.summary or body[:120]).replace("\n", " "),
                ),
                tags=_extract_tags(body),
                chunk=NoteChunk(parent_note_id=parent.id, index=i, source_span=f"{start}-{end}"),
                preextract=NotePreExtract(
                    graph_worthy=section.graph_worthy,
                    status="ok",
                    topic=section.topic or None,
                ),
                updated_at=local_now(),
            )
        )
    return chunks


def enrich_node(state: AgentState, store: PostgresMemoryStore) -> AgentState:
    if state.note is None:
        return state

    state.note.body.summary = summarize_text(state.note.body.content)
    if not state.note.tags:
        state.note.tags = _extract_tags(state.note.body.content)
    return state


def link_node(state: AgentState, store: PostgresMemoryStore) -> AgentState:
    if state.note is None:
        return state

    matches = store.find_similar_notes(state.note.user_id, state.note.body.content)
    state.matches = matches
    state.note.related_note_ids = [match.id for match in matches]
    store.add_note(state.note)
    for chunk in state.chunk_notes:
        store.add_note(chunk)
    return state


def schedule_review_node(state: AgentState, store: PostgresMemoryStore) -> AgentState:
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


def answer_node(state: AgentState, store: PostgresMemoryStore) -> AgentState:
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


def digest_node(store: PostgresMemoryStore, user_id: str) -> str:
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
