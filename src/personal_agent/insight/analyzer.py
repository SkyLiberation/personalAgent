"""Deterministic knowledge gap detection over the graph + local notes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal

if TYPE_CHECKING:
    from personal_agent.graphiti.store import GraphitiStore
    from personal_agent.memory import MemoryFacade

logger = logging.getLogger(__name__)

GapType = Literal["isolated_entity", "potential_conflict"]

# Shared with the verifier's heuristic: presence of these markers flips the
# polarity of a statement. Two similar notes with opposite polarity on the same
# subject are a candidate contradiction worth asking about.
_NEGATION_MARKERS = ("不", "没有", "未", "不能", "无法", "不会", "不是", "no ", "not ")


def _has_negation(text: str) -> bool:
    return any(marker in text for marker in _NEGATION_MARKERS)


@dataclass(slots=True)
class KnowledgeGap:
    """A detected gap in the knowledge base worth a proactive question."""

    gap_type: GapType
    # Stable key for idempotency (one question per gap per day).
    key: str
    question: str
    entities: list[str] = field(default_factory=list)
    note_ids: list[str] = field(default_factory=list)


class KnowledgeGapAnalyzer:
    """Find knowledge islands and potential contradictions.

    Detection is deterministic:

    - *Isolated entity*: an entity present in the graph with a connection
      degree at or below ``min_degree``. It exists but is barely linked to the
      rest of what you know, so a question that asks how it relates to other
      concepts grows the graph.
    - *Potential conflict*: two recent notes that look like they talk about the
      same thing (lexical title overlap) but have opposite polarity. Surfaced so
      the user can reconcile them. This never auto-marks a conflict — it only
      asks.

    Question phrasing is template-based by default. An optional ``question_llm``
    callable may rewrite the question; failures fall back to the template.
    """

    def __init__(
        self,
        memory: "MemoryFacade",
        graph_store: "GraphitiStore | None" = None,
        *,
        min_degree: int = 1,
        max_gaps: int = 3,
        recent_note_limit: int = 30,
        question_llm: "Callable[[KnowledgeGap], str | None] | None" = None,
    ) -> None:
        self.memory = memory
        self.graph_store = graph_store
        self.min_degree = max(0, min_degree)
        self.max_gaps = max(1, max_gaps)
        self.recent_note_limit = max(1, recent_note_limit)
        # Optional LLM rewriter for question phrasing. Detection stays
        # deterministic; only the user-facing wording may be improved. A None
        # return (or any failure) keeps the deterministic template question.
        self.question_llm = question_llm

    def detect(self, user_id: str) -> list[KnowledgeGap]:
        gaps: list[KnowledgeGap] = []
        gaps.extend(self._isolated_entities(user_id))
        gaps.extend(self._potential_conflicts(user_id))
        gaps = gaps[: self.max_gaps]
        if self.question_llm is not None:
            for gap in gaps:
                gap.question = self._rephrase_question(gap)
        return gaps

    def _rephrase_question(self, gap: KnowledgeGap) -> str:
        """Best-effort LLM rewrite of the question; falls back to the template."""
        try:
            rewritten = self.question_llm(gap)
        except Exception:
            logger.warning("Knowledge gap question rewrite failed", exc_info=True)
            return gap.question
        if rewritten and rewritten.strip():
            return rewritten.strip()
        return gap.question

    # -- isolated entities --------------------------------------------------

    def _isolated_entities(self, user_id: str) -> list[KnowledgeGap]:
        if self.graph_store is None:
            return []
        try:
            topology = self.graph_store.get_topology(user_id)
        except Exception:
            logger.warning("Knowledge gap: get_topology failed", exc_info=True)
            return []
        if topology.get("error"):
            return []

        nodes = topology.get("nodes") or []
        links = topology.get("links") or []
        if not nodes:
            return []

        degree: dict[str, int] = {node.get("id"): 0 for node in nodes if node.get("id")}
        for link in links:
            for endpoint in (link.get("source"), link.get("target")):
                if endpoint in degree:
                    degree[endpoint] += 1

        name_by_id = {node.get("id"): (node.get("name") or "") for node in nodes}
        gaps: list[KnowledgeGap] = []
        # Lowest-degree first: the most isolated concepts are the best questions.
        for node_id, deg in sorted(degree.items(), key=lambda kv: kv[1]):
            if deg > self.min_degree:
                break
            name = name_by_id.get(node_id, "").strip()
            if not name:
                continue
            gaps.append(KnowledgeGap(
                gap_type="isolated_entity",
                key=f"isolated:{node_id}",
                question=f"你记录过「{name}」，但它和其他知识几乎没有关联。它和你关注的哪些概念有关系？补充一下可以让这块知识连起来。",
                entities=[name],
            ))
            if len(gaps) >= self.max_gaps:
                break
        return gaps

    # -- potential conflicts ------------------------------------------------

    def _potential_conflicts(self, user_id: str) -> list[KnowledgeGap]:
        notes = self.memory.list_recent_notes(
            user_id, limit=self.recent_note_limit, include_chunks=False
        )
        gaps: list[KnowledgeGap] = []
        seen_pairs: set[frozenset[str]] = set()
        for i, note_a in enumerate(notes):
            for note_b in notes[i + 1:]:
                pair = frozenset({note_a.id, note_b.id})
                if pair in seen_pairs:
                    continue
                if not self._titles_overlap(note_a.body.title, note_b.body.title):
                    continue
                text_a = f"{note_a.body.title} {note_a.body.summary}"
                text_b = f"{note_b.body.title} {note_b.body.summary}"
                if _has_negation(text_a) == _has_negation(text_b):
                    continue
                seen_pairs.add(pair)
                gaps.append(KnowledgeGap(
                    gap_type="potential_conflict",
                    key=f"conflict:{min(note_a.id, note_b.id)}:{max(note_a.id, note_b.id)}",
                    question=(
                        f"这两条笔记看起来有冲突：「{note_a.body.title}」和「{note_b.body.title}」。"
                        "哪一条更准确？回复后我可以帮你更新。"
                    ),
                    note_ids=[note_a.id, note_b.id],
                ))
                if len(gaps) >= self.max_gaps:
                    return gaps
        return gaps

    @staticmethod
    def _titles_overlap(title_a: str, title_b: str, *, min_shared: int = 2) -> bool:
        """Cheap lexical overlap on title tokens (2+ char tokens)."""
        tokens_a = {t for t in title_a.split() if len(t) >= 2}
        tokens_b = {t for t in title_b.split() if len(t) >= 2}
        if not tokens_a or not tokens_b:
            return False
        return len(tokens_a & tokens_b) >= min_shared
