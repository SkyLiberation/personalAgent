from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .config import Settings
from .graph import build_ask_graph, build_capture_graph
from .graphiti_store import GraphAskResult, GraphCaptureResult, GraphCitationHit, GraphitiStore
from .memory_store import LocalMemoryStore
from .models import AgentState, Citation, KnowledgeNote, RawIngestItem, ReviewCard
from .nodes import digest_node


class CaptureResult(BaseModel):
    note: KnowledgeNote
    related_notes: list[KnowledgeNote] = Field(default_factory=list)
    review_card: ReviewCard | None = None
    graph_enabled: bool = False


class AskResult(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    matches: list[KnowledgeNote] = Field(default_factory=list)
    graph_enabled: bool = False


class DigestResult(BaseModel):
    message: str
    recent_notes: list[KnowledgeNote] = Field(default_factory=list)
    due_reviews: list[ReviewCard] = Field(default_factory=list)


class AgentService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.store = LocalMemoryStore(self.settings.data_dir)
        self.graph_store = GraphitiStore(self.settings)

    def capture(self, text: str, source_type: str = "text", user_id: str | None = None) -> CaptureResult:
        normalized_user = user_id or self.settings.default_user
        graph = build_capture_graph(self.store)
        state = AgentState(
            mode="capture",
            user_id=normalized_user,
            raw_item=RawIngestItem(content=text, source_type=source_type, user_id=normalized_user),
        )
        result = AgentState.model_validate(graph.invoke(state))
        if result.note is None:
            raise ValueError("Capture flow did not produce a note.")

        graph_result = self.graph_store.ingest_note(result.note)
        related_notes = result.matches
        if graph_result.enabled:
            updated_note = self._merge_graph_capture(result.note, graph_result)
            self.store.update_note(updated_note)
            result.note = updated_note
            graph_related_notes = self.store.find_notes_by_graph_episode_uuids(
                normalized_user, graph_result.related_episode_uuids
            )
            related_notes = _merge_notes(graph_related_notes, related_notes)
            updated_note.related_note_ids = [note.id for note in related_notes if note.id != updated_note.id]
            updated_note.updated_at = datetime.utcnow()
            self.store.update_note(updated_note)
            result.note = updated_note

        return CaptureResult(
            note=result.note,
            related_notes=related_notes,
            review_card=result.review_card,
            graph_enabled=graph_result.enabled,
        )

    def ask(self, question: str, user_id: str | None = None) -> AskResult:
        normalized_user = user_id or self.settings.default_user

        graph_result = self.graph_store.ask(question, normalized_user)
        if graph_result.enabled and graph_result.answer:
            matches, citations = self._graph_matches_and_citations(normalized_user, graph_result)
            answer = self._compose_graph_answer(question, graph_result, matches)
            return AskResult(
                answer=answer,
                citations=citations,
                matches=matches,
                graph_enabled=True,
            )

        graph = build_ask_graph(self.store)
        state = AgentState(mode="ask", question=question, user_id=normalized_user)
        result = AgentState.model_validate(graph.invoke(state))
        return AskResult(
            answer=result.answer or "暂时没有生成答案。",
            citations=result.citations,
            matches=result.matches,
            graph_enabled=False,
        )

    def digest(self, user_id: str | None = None) -> DigestResult:
        normalized_user = user_id or self.settings.default_user
        return DigestResult(
            message=digest_node(self.store, normalized_user),
            recent_notes=self.store.list_notes(normalized_user)[-5:],
            due_reviews=self.store.due_reviews(normalized_user),
        )

    def list_notes(self, user_id: str | None = None) -> list[KnowledgeNote]:
        normalized_user = user_id or self.settings.default_user
        return list(reversed(self.store.list_notes(normalized_user)))

    def health(self) -> dict[str, object]:
        graph_status = self.graph_store.status()
        return {
            "status": "ok",
            "graphiti": graph_status,
        }

    def _merge_graph_capture(
        self, note: KnowledgeNote, graph_result: GraphCaptureResult
    ) -> KnowledgeNote:
        note.graph_episode_uuid = graph_result.episode_uuid
        note.entity_names = graph_result.entity_names
        note.relation_facts = graph_result.relation_facts[:8]
        note.updated_at = datetime.utcnow()
        return note

    def _graph_citations(
        self, matches: list[KnowledgeNote], graph_result: GraphAskResult
    ) -> list[Citation]:
        citations: list[Citation] = []
        facts = graph_result.relation_facts
        for index, note in enumerate(matches[:5]):
            citations.append(
                Citation(
                    note_id=note.id,
                    title=note.title,
                    snippet=note.summary[:120],
                    relation_fact=facts[index] if index < len(facts) else None,
                )
            )
        return citations

    def _graph_matches_and_citations(
        self, user_id: str, graph_result: GraphAskResult
    ) -> tuple[list[KnowledgeNote], list[Citation]]:
        matches = self.store.find_notes_by_graph_episode_uuids(
            user_id, graph_result.related_episode_uuids
        )
        if not graph_result.citation_hits:
            return matches, self._graph_citations(matches, graph_result)

        notes_by_episode_uuid = {
            note.graph_episode_uuid: note for note in matches if note.graph_episode_uuid is not None
        }
        citations: list[Citation] = []
        matched_notes: list[KnowledgeNote] = []
        seen_note_ids: set[str] = set()
        seen_citation_keys: set[tuple[str, str]] = set()

        for hit in graph_result.citation_hits:
            note = notes_by_episode_uuid.get(hit.episode_uuid)
            if note is None:
                continue
            citation_key = (note.id, hit.relation_fact)
            if citation_key not in seen_citation_keys:
                citations.append(
                    Citation(
                        note_id=note.id,
                        title=note.title,
                        snippet=_best_snippet(note, hit),
                        relation_fact=hit.relation_fact,
                    )
                )
                seen_citation_keys.add(citation_key)
            if note.id not in seen_note_ids:
                matched_notes.append(note)
                seen_note_ids.add(note.id)
            if len(citations) >= 5:
                break

        for note in matches:
            if note.id in seen_note_ids:
                continue
            matched_notes.append(note)
            seen_note_ids.add(note.id)

        return matched_notes, citations

    def _compose_graph_answer(
        self, question: str, graph_result: GraphAskResult, matches: list[KnowledgeNote]
    ) -> str:
        focus_entities = [
            entity_name
            for entity_name in graph_result.entity_names
            if len(entity_name) >= 2 and entity_name in question
        ]
        merged_facts = list(graph_result.relation_facts)
        for note in matches[:3]:
            for fact in note.relation_facts:
                if focus_entities and not any(entity_name in fact for entity_name in focus_entities):
                    continue
                if fact not in merged_facts:
                    merged_facts.append(fact)

        if not merged_facts:
            return graph_result.answer or "暂时没有生成答案。"

        top_entities = "、".join(graph_result.entity_names[:5]) if graph_result.entity_names else "暂无实体摘要"
        fact_lines = "\n".join(f"- {fact}" for fact in merged_facts[:5])
        return f"图谱里最相关的实体：{top_entities}\n关联事实：\n{fact_lines}"


def _merge_notes(primary: list[KnowledgeNote], secondary: list[KnowledgeNote]) -> list[KnowledgeNote]:
    merged: list[KnowledgeNote] = []
    seen: set[str] = set()
    for note in [*primary, *secondary]:
        if note.id in seen:
            continue
        seen.add(note.id)
        merged.append(note)
    return merged


def _best_snippet(note: KnowledgeNote, hit: GraphCitationHit) -> str:
    for part in _split_sentences(note.content):
        if hit.relation_fact in part:
            return part[:120]
    for entity_name in note.entity_names:
        if len(entity_name) >= 2 and entity_name in hit.relation_fact:
            for part in _split_sentences(note.content):
                if entity_name in part:
                    return part[:120]
    return note.summary[:120]


def _split_sentences(text: str) -> list[str]:
    normalized = text.replace("\r", "\n")
    parts: list[str] = []
    current = ""
    for char in normalized:
        current += char
        if char in {"。", "！", "？", ".", "!", "?", "\n"}:
            stripped = current.strip()
            if stripped:
                parts.append(stripped)
            current = ""
    if current.strip():
        parts.append(current.strip())
    return parts
