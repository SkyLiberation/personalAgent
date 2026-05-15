from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field


class GraphCitationHit(BaseModel):
    episode_uuid: str
    relation_fact: str
    endpoint_names: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    entity_overlap_count: int = 0
    score: int = 0


def rank_graph_citation_hits(
    question: str,
    edges: Iterable[Any],
    node_names_by_uuid: dict[str, str],
    *,
    limit: int | None = 12,
) -> list[GraphCitationHit]:
    """Convert Graphiti edges into focused, episode-addressable citation hits.

    This is intentionally independent from GraphitiStore. It only relies on
    edge-like objects exposing fact/source_node_uuid/target_node_uuid/episodes.
    """
    ranked_hits = _rank_graph_hits(question, edges, node_names_by_uuid)
    focused_hits = _select_focus_hits(question, ranked_hits)
    if limit is None:
        return focused_hits
    return focused_hits[: max(0, limit)]


def _rank_graph_hits(
    question: str,
    edges: Iterable[Any],
    node_names_by_uuid: dict[str, str],
) -> list[GraphCitationHit]:
    scored_hits: list[GraphCitationHit] = []
    query_bigrams = _character_bigrams(question)
    normalized_question = _normalize_text(question)
    query_keywords = _extract_keywords(question)

    for edge in edges:
        relation_fact = str(getattr(edge, "fact", "") or "").strip()
        if not relation_fact:
            continue

        endpoint_names = [
            node_names_by_uuid.get(str(getattr(edge, "source_node_uuid", "") or ""), ""),
            node_names_by_uuid.get(str(getattr(edge, "target_node_uuid", "") or ""), ""),
        ]
        relation_score, matched_terms, entity_overlap_count = _score_relation_fact(
            normalized_question,
            query_bigrams,
            query_keywords,
            relation_fact,
            endpoint_names,
        )

        for episode_uuid in getattr(edge, "episodes", []) or []:
            scored_hits.append(
                GraphCitationHit(
                    episode_uuid=str(episode_uuid),
                    relation_fact=relation_fact,
                    endpoint_names=[name for name in endpoint_names if name],
                    matched_terms=matched_terms,
                    entity_overlap_count=entity_overlap_count,
                    score=relation_score,
                )
            )

    scored_hits.sort(
        key=lambda hit: (
            hit.entity_overlap_count,
            len(hit.matched_terms),
            hit.score,
            len(hit.relation_fact),
        ),
        reverse=True,
    )
    return _dedupe_citation_hits(scored_hits)


def _score_relation_fact(
    normalized_question: str,
    query_bigrams: set[str],
    query_keywords: list[str],
    relation_fact: str,
    endpoint_names: list[str],
) -> tuple[int, list[str], int]:
    normalized_fact = _normalize_text(relation_fact)
    fact_bigrams = _character_bigrams(relation_fact)
    overlap_score = len(query_bigrams & fact_bigrams)
    direct_match_score = 4 if normalized_question and (
        normalized_question in normalized_fact or normalized_fact in normalized_question
    ) else 0

    endpoint_score = 0
    entity_overlap_count = 0
    for name in endpoint_names:
        normalized_name = _normalize_text(name)
        if len(normalized_name) >= 2 and normalized_name in normalized_question:
            endpoint_score += 6
            entity_overlap_count += 1

    matched_terms: list[str] = []
    keyword_score = 0
    for keyword in query_keywords:
        if keyword in relation_fact and keyword not in matched_terms:
            matched_terms.append(keyword)
            keyword_score += 5 if len(keyword) >= 4 else 3

    relation_bonus = _relation_phrase_score(query_keywords, relation_fact)
    total_score = endpoint_score + direct_match_score + overlap_score + keyword_score + relation_bonus
    return total_score, matched_terms, entity_overlap_count


def _dedupe_citation_hits(hits: list[GraphCitationHit]) -> list[GraphCitationHit]:
    deduped: list[GraphCitationHit] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        key = (hit.episode_uuid, hit.relation_fact)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
    return deduped


def _select_focus_hits(question: str, hits: list[GraphCitationHit]) -> list[GraphCitationHit]:
    if not hits:
        return []
    question_keywords = _extract_keywords(question)
    entity_hits = [hit for hit in hits if hit.entity_overlap_count > 0]
    if entity_hits:
        hits = entity_hits
    keyword_hits = [
        hit
        for hit in hits
        if any(_normalize_text(keyword) in _normalize_text(hit.relation_fact) for keyword in question_keywords)
    ]
    if keyword_hits:
        hits = keyword_hits
    top_score = hits[0].score
    if top_score <= 0:
        return hits
    threshold = max(1, top_score - 3)
    focused_hits = [hit for hit in hits if hit.score >= threshold]
    return focused_hits or hits


def _character_bigrams(text: str) -> set[str]:
    normalized = _normalize_text(text)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def _normalize_text(text: str) -> str:
    return "".join(char.lower() for char in text if char.isalnum())


def _extract_keywords(text: str) -> list[str]:
    keywords: list[str] = []
    ascii_buffer = ""
    cjk_buffer = ""
    for char in text:
        if char.isascii() and (char.isalnum() or char in {"_", "-"}):
            if cjk_buffer:
                _append_keyword(keywords, cjk_buffer)
                cjk_buffer = ""
            ascii_buffer += char.lower()
            continue
        if ascii_buffer:
            _append_keyword(keywords, ascii_buffer)
            ascii_buffer = ""
        if _is_cjk(char):
            cjk_buffer += char
            continue
        if cjk_buffer:
            _append_keyword(keywords, cjk_buffer)
            cjk_buffer = ""
    if ascii_buffer:
        _append_keyword(keywords, ascii_buffer)
    if cjk_buffer:
        _append_keyword(keywords, cjk_buffer)
    return keywords


def _keep_keyword(token: str) -> bool:
    if len(token) >= 2 and not token.isascii():
        return True
    if len(token) < 2:
        return False
    return token not in {
        "什么",
        "哪些",
        "哪个",
        "这个",
        "那个",
        "一下",
        "一下子",
        "about",
        "from",
        "into",
        "that",
        "this",
        "with",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "how",
        "the",
        "and",
        "for",
        "are",
        "was",
        "were",
        "is",
    }


def _relation_phrase_score(query_keywords: list[str], relation_fact: str) -> int:
    score = 0
    normalized_fact = _normalize_text(relation_fact)
    for left, right in zip(query_keywords, query_keywords[1:]):
        if len(left) < 2 or len(right) < 2:
            continue
        compact_pair = _normalize_text(left + right)
        if compact_pair and compact_pair in normalized_fact:
            score += 4
    return score


def _append_keyword(target: list[str], token: str) -> None:
    normalized = token.strip().lower()
    if _keep_keyword(normalized) and normalized not in target:
        target.append(normalized)


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"
