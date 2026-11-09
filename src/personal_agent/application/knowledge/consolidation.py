"""Application use case for topic-level knowledge consolidation."""

from __future__ import annotations

import logging
from typing import Callable

from pydantic import BaseModel, Field

from personal_agent.kernel.models import KnowledgeNote
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS
from personal_agent.memory import MemoryFacade

logger = logging.getLogger(__name__)


class ConsolidationResult(BaseModel):
    ok: bool
    topic: str
    note_id: str = ""
    title: str = ""
    summary: str = ""
    source_note_ids: list[str] = Field(default_factory=list)
    superseded: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    error: str = ""


class KnowledgeConsolidationUseCase:
    """Select topic notes, synthesize one review note, supersede the sources."""

    def __init__(
        self,
        memory: MemoryFacade,
        *,
        capture: Callable[..., object],
        generate_draft: Callable[[str], str | None],
        prompts: PromptCatalog = DEFAULT_PROMPTS,
    ) -> None:
        self._prompts = prompts
        self._memory = memory
        self._capture = capture
        self._generate_draft = generate_draft

    def execute(
        self,
        *,
        topic: str,
        user_id: str,
        note_ids: list[str] | None = None,
    ) -> ConsolidationResult:
        normalized_topic = topic.strip()
        if not normalized_topic:
            return ConsolidationResult(
                ok=False,
                topic="",
                error=self._prompts.render('knowledge.consolidation.topic_missing'),
            )

        sources = self._load_sources(
            normalized_topic,
            user_id=user_id,
            note_ids=note_ids,
        )
        if len(sources) < 2:
            return ConsolidationResult(
                ok=False,
                topic=normalized_topic,
                source_note_ids=[note.id for note in sources],
                error=self._prompts.render('knowledge.consolidation.notes_missing'),
            )

        draft = self._draft(normalized_topic, sources)
        if not draft:
            return ConsolidationResult(
                ok=False,
                topic=normalized_topic,
                source_note_ids=[note.id for note in sources],
                error=self._prompts.render('knowledge.consolidation.draft_missing'),
            )

        captured = self._capture(
            text=draft,
            source_type="note",
            user_id=user_id,
        )
        new_note = captured.note
        superseded: list[str] = []
        failed: list[str] = []
        for note in sources:
            try:
                self._memory.supersede_note(
                    note.id,
                    new_note.id,
                    user_id=user_id,
                    reason=f"整理进主题综述「{normalized_topic}」",
                )
                superseded.append(note.id)
            except Exception:
                logger.exception(
                    "Supersede failed during consolidation note_id=%s",
                    note.id,
                )
                failed.append(note.id)

        return ConsolidationResult(
            ok=True,
            topic=normalized_topic,
            note_id=new_note.id,
            title=new_note.body.title,
            summary=new_note.body.summary,
            source_note_ids=[note.id for note in sources],
            superseded=superseded,
            failed=failed,
        )

    def _load_sources(
        self,
        topic: str,
        *,
        user_id: str,
        note_ids: list[str] | None,
    ) -> list[KnowledgeNote]:
        if note_ids:
            candidates = [
                self._memory.get_note(note_id, user_id=user_id)
                for note_id in dict.fromkeys(note_ids)
            ]
        else:
            candidates = self._memory.search_memory(user_id, topic, limit=12)

        sources: list[KnowledgeNote] = []
        seen: set[str] = set()
        for note in candidates:
            if note is None:
                continue
            parent_id = note.chunk.parent_note_id
            if parent_id:
                note = self._memory.get_note(parent_id, user_id=user_id) or note
            if note.id in seen or note.version.status != "current":
                continue
            seen.add(note.id)
            sources.append(note)
        return sources

    def _draft(self, topic: str, sources: list[KnowledgeNote]) -> str:
        blocks = [
            self._prompts.render("knowledge.consolidation.source", index=index, title=note.body.title, content=note.body.content)
            for index, note in enumerate(sources, start=1)
        ]
        joined = "\n\n".join(blocks)
        prompt = (
            self._prompts.render('knowledge.consolidation.draft', topic=topic, sources=joined)
        )
        return self._generate_draft(prompt) or f"# {topic}（综述）\n\n{joined}"
