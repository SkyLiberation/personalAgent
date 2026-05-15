from __future__ import annotations

from ..core.models import Citation, KnowledgeNote
from ..graphiti.reranker import GraphCitationHit
from ..graphiti.store import GraphAskResult
from .verifier import VerificationResult

def _annotate_answer(answer: str, verification: VerificationResult) -> str:
    if verification.ok and verification.sufficient:
        return answer
    notes: list[str] = []
    if verification.issues:
        notes.append("(校验提示: " + "; ".join(verification.issues) + ")")
    if verification.warnings:
        notes.append("(注意: " + "; ".join(verification.warnings[:2]) + ")")
    if not notes:
        return answer
    return answer + "\n\n---\n" + "\n".join(notes)


def _merge_notes(primary: list[KnowledgeNote], secondary: list[KnowledgeNote]) -> list[KnowledgeNote]:
    merged: list[KnowledgeNote] = []
    seen: set[str] = set()
    for note in [*primary, *secondary]:
        if note.id in seen:
            continue
        seen.add(note.id)
        merged.append(note)
    return merged


def _merge_citations(primary: list[Citation], secondary: list[Citation]) -> list[Citation]:
    merged: list[Citation] = []
    seen: set[tuple[str, str, str]] = set()
    for citation in [*primary, *secondary]:
        key = (citation.note_id, citation.relation_fact or "", citation.snippet)
        if key in seen:
            continue
        seen.add(key)
        merged.append(citation)
    return merged


def _graph_episode_uuids(graph_result: GraphAskResult) -> list[str]:
    ordered: list[str] = []

    def add(value: str | None) -> None:
        if value and value not in ordered:
            ordered.append(value)

    for hit in graph_result.citation_hits:
        add(hit.episode_uuid)
    for fact_ref in graph_result.fact_refs:
        for episode_uuid in fact_ref.episode_uuids:
            add(episode_uuid)
    for edge_ref in graph_result.edge_refs:
        for episode_uuid in edge_ref.episodes:
            add(episode_uuid)
    for episode_uuid in graph_result.related_episode_uuids:
        add(episode_uuid)
    return ordered


def _graph_facts_by_episode(graph_result: GraphAskResult) -> dict[str, list[str]]:
    facts_by_episode: dict[str, list[str]] = {}

    def add(episode_uuid: str, fact: str) -> None:
        normalized = fact.strip()
        if not episode_uuid or not normalized:
            return
        facts = facts_by_episode.setdefault(episode_uuid, [])
        if normalized not in facts:
            facts.append(normalized)

    for hit in graph_result.citation_hits:
        add(hit.episode_uuid, hit.relation_fact)
    for fact_ref in graph_result.fact_refs:
        for episode_uuid in fact_ref.episode_uuids:
            add(episode_uuid, fact_ref.fact)
    for edge_ref in graph_result.edge_refs:
        for episode_uuid in edge_ref.episodes:
            add(episode_uuid, edge_ref.fact)
    return facts_by_episode


def _graph_fact_lines(graph_result: GraphAskResult, limit: int = 8) -> list[str]:
    facts: list[str] = []

    def add(value: str | None) -> None:
        normalized = (value or "").strip()
        if normalized and normalized not in facts:
            facts.append(normalized)

    for fact_ref in graph_result.fact_refs:
        add(fact_ref.fact)
    for edge_ref in graph_result.edge_refs:
        add(edge_ref.fact)
    for hit in graph_result.citation_hits:
        add(hit.relation_fact)
    for fact in graph_result.relation_facts:
        add(fact)
    return facts[:limit]


def _format_graph_relation(fact: str, source: str = "", target: str = "", snippet: str | None = None) -> str:
    endpoints = ""
    if source and target:
        endpoints = f"{source} -> {target}: "
    elif source:
        endpoints = f"{source}: "
    line = f"- {endpoints}{fact}"
    if snippet:
        line += f" [原文: {snippet[:100]}]"
    return line


def _best_snippet(note: KnowledgeNote, hit: GraphCitationHit, question: str) -> str:
    """Select the sentence from note content that best anchors the graph relation_fact.

    Uses word-overlap scoring between the relation_fact and each sentence,
    weighted by entity name matches and question keyword relevance.
    Falls back to note summary when no sentence reaches the minimum score.
    """
    best_part = ""
    best_score = -1
    question_keywords = _extract_question_keywords(question)
    fact_tokens = _tokenize_for_overlap(hit.relation_fact)
    entity_names = [n for n in (hit.endpoint_names or note.entity_names or []) if len(n) >= 2]

    for part in _split_sentences(note.content):
        if len(part) < 10:
            continue
        score = 0
        # Word overlap between relation_fact and this sentence (primary anchor)
        if fact_tokens:
            part_tokens = _tokenize_for_overlap(part)
            if part_tokens:
                overlap = len(fact_tokens & part_tokens)
                score += min(overlap * 5, 30)  # cap at 30 points for overlap
        # Legacy exact match bonus
        if hit.relation_fact and hit.relation_fact in part:
            score += 10
        # Entity name matches (strong signal)
        for entity_name in entity_names:
            if entity_name in part:
                score += 5
        # Question keyword relevance
        for keyword in question_keywords:
            if keyword in part:
                score += 2
        if score > best_score:
            best_part = part
            best_score = score

    if best_part and best_score >= 3:
        return best_part[:160]
    # Weak anchoring: return summary with a marker
    if best_part:
        return best_part[:160]
    return note.summary[:160]


def _tokenize_for_overlap(text: str) -> set[str]:
    """Tokenize text into lowercased meaningful words for overlap scoring."""
    if not text:
        return set()
    # Simple tokenization: split on non-alphanumeric, filter short tokens
    tokens: set[str] = set()
    for token in text.lower().split():
        # Strip punctuation from each token
        cleaned = "".join(c for c in token if c.isalnum())
        if len(cleaned) >= 2:
            tokens.add(cleaned)
    return tokens


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


def _extract_question_keywords(question: str) -> list[str]:
    keywords: list[str] = []
    buffer = ""
    for char in question:
        if char.isascii() and (char.isalnum() or char in {"_", "-"}):
            buffer += char.lower()
            continue
        if buffer:
            if len(buffer) >= 2 and buffer not in keywords:
                keywords.append(buffer)
            buffer = ""
    if buffer and len(buffer) >= 2 and buffer not in keywords:
        keywords.append(buffer)
    compact = question.replace("？", " ").replace("。", " ").replace("，", " ").replace(",", " ")
    for chunk in compact.split():
        normalized = chunk.strip()
        if len(normalized) >= 2 and not normalized.isascii() and normalized not in keywords:
            keywords.append(normalized)
    return keywords[:8]


def _evidence_content(note: KnowledgeNote) -> str:
    """Return the best content for evidence display.

    Parent notes (with chunks) use only summary to avoid dumping entire
    documents into prompts. Chunk notes and standalone short notes use
    content directly.
    """
    if note.parent_note_id is not None:
        # Chunk note — content is already focused
        return note.content[:500]
    if note.chunk_index == 0:
        # Parent note — use summary to keep prompts compact
        return note.summary
    # Standalone note — use content
    return note.content[:500]


def _top_sentences(text: str, limit: int = 3) -> list[str]:
    sentences = _split_sentences(text)
    scored: list[tuple[int, str]] = []
    for sentence in sentences:
        compact = sentence.strip()
        if not compact:
            continue
        score = len(compact)
        if any(token in compact for token in ["是", "包括", "通过", "用于", "因为", "所以", "导致", "机制", "原理"]):
            score += 20
        scored.append((score, compact))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [sentence[:180] for _, sentence in scored[:limit]]

