from __future__ import annotations

import re
from datetime import datetime
from hashlib import blake2b
from math import sqrt

from personal_agent.kernel.models import KnowledgeNote, MemoryEpisode, MemoryItem
from personal_agent.kernel.projections import retrieval_document_from_note
from personal_agent.kernel.query_understanding import RetrievalFilters

EMBEDDING_DIMENSIONS = 128
BM25_TOKENIZER = "chinese_compatible"
BM25_KEY_FIELD = "id"
BM25_TEXT_FIELD = "search_text"


def bm25_text_fields_json() -> str:
    return (
        '{"' + BM25_TEXT_FIELD + '": {"tokenizer": {"type": "'
        + BM25_TOKENIZER + '"}}}'
    )


def compact_whitespace(value: str) -> str:
    return " ".join(value.split())


def search_text_for_note(note: KnowledgeNote) -> str:
    document = retrieval_document_from_note(note)
    parts = [
        document.title,
        document.summary,
        document.preextract_topic or "",
        " ".join(document.tags),
        " ".join(document.entity_names),
        " ".join(document.relation_facts),
        " ".join(str(value) for value in document.metadata.values() if value),
        document.source_fingerprint or "",
        document.content,
    ]
    return compact_whitespace(" ".join(part for part in parts if part))


def search_text_for_episode(episode: MemoryEpisode) -> str:
    parts = [
        episode.title,
        episode.summary,
        episode.workflow,
        episode.outcome,
        episode.entry_text,
        " ".join(episode.decisions),
        " ".join(episode.open_items),
        " ".join(episode.tool_refs),
        " ".join(episode.note_refs),
        " ".join(str(value) for value in episode.metadata.values() if value),
    ]
    return compact_whitespace(" ".join(part for part in parts if part))


def search_text_for_memory_item(item: MemoryItem) -> str:
    parts = [
        item.memory_type,
        item.title,
        item.content,
        item.status,
        " ".join(item.applies_to),
        " ".join(item.source_episode_ids),
        " ".join(item.source_run_ids),
        " ".join(item.evidence_refs),
        " ".join(str(value) for value in item.metadata.values() if value),
    ]
    return compact_whitespace(" ".join(part for part in parts if part))


def bm25_bonus(score: float) -> float:
    if score <= 0.0:
        return 0.0
    return 0.016 * (score / (score + 8.0))


def query_terms(query: str) -> list[str]:
    normalized = query.lower()
    terms: list[str] = []

    for token in re.findall(r"[a-z0-9_+-]{2,}", normalized):
        if token not in terms:
            terms.append(token)

    cjk_runs = re.findall(r"[\u3400-\u9fff]{2,}", query)
    for run in cjk_runs:
        if run not in terms:
            terms.append(run)
        for size in (2, 3):
            for index in range(0, max(0, len(run) - size + 1)):
                gram = run[index:index + size]
                if gram not in terms:
                    terms.append(gram)

    for token in query.replace("？", " ").replace("，", " ").replace(",", " ").split():
        cleaned = token.strip().lower()
        if len(cleaned) >= 2 and cleaned not in terms:
            terms.append(cleaned)

    return terms[:16]


def embedding_features(text: str) -> list[str]:
    features = query_terms(text)
    compact_cjk = "".join(re.findall(r"[\u3400-\u9fff]", text))
    for size in (2, 3, 4):
        for index in range(0, max(0, len(compact_cjk) - size + 1)):
            gram = compact_cjk[index:index + size]
            if gram not in features:
                features.append(gram)
    return features[:512]


def local_embedding(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    for feature in embedding_features(text.lower()):
        digest = blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [round(value / norm, 6) for value in vector]


def vector_literal(vector: list[float] | None) -> str | None:
    if vector is None:
        return None
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"


def filters_sql(filters: RetrievalFilters | None) -> tuple[str, list[object]]:
    if filters is None or not filters.active():
        return "", []

    clauses: list[str] = []
    params: list[object] = []

    source_types = [item.strip() for item in filters.source_types if item.strip()]
    if source_types:
        clauses.append("AND payload#>>'{source,type}' = ANY(%s)")
        params.append(source_types)

    if filters.source_ref_contains.strip():
        clauses.append("AND lower(coalesce(payload#>>'{source,ref}', '')) LIKE %s")
        params.append(f"%{filters.source_ref_contains.strip().lower()}%")

    tags = [tag.strip().lower() for tag in filters.tags if tag.strip()]
    if tags:
        clauses.append(
            """
            AND EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(coalesce(payload->'tags', '[]'::jsonb)) AS tag(value)
                WHERE lower(tag.value) = ANY(%s)
            )
            """
        )
        params.append(tags)

    if filters.created_after.strip():
        clauses.append("AND created_at >= %s::timestamptz")
        params.append(filters.created_after.strip())

    if filters.created_before.strip():
        clauses.append("AND created_at <= %s::timestamptz")
        params.append(filters.created_before.strip())

    if filters.metadata_contains.strip():
        clauses.append("AND lower(coalesce(payload#>>'{source,metadata}', '')) LIKE %s")
        params.append(f"%{filters.metadata_contains.strip().lower()}%")

    if filters.parent_note_id.strip():
        clauses.append("AND (id = %s OR parent_note_id = %s)")
        params.extend([filters.parent_note_id.strip(), filters.parent_note_id.strip()])

    return "\n".join(clauses), params


def note_matches_filters(note: KnowledgeNote, filters: RetrievalFilters | None) -> bool:
    if filters is None or not filters.active():
        return True
    if filters.source_types and note.source.type not in filters.source_types:
        return False
    if filters.source_ref_contains.strip():
        needle = filters.source_ref_contains.strip().lower()
        if needle not in (note.source.ref or "").lower():
            return False
    if filters.tags:
        note_tags = {tag.lower() for tag in note.tags}
        if not all(tag.lower() in note_tags for tag in filters.tags):
            return False
    if filters.metadata_contains.strip():
        metadata_text = " ".join(str(value) for value in note.source.metadata.values()).lower()
        if filters.metadata_contains.strip().lower() not in metadata_text:
            return False
    if filters.created_after.strip():
        try:
            if note.created_at < datetime.fromisoformat(filters.created_after.strip()):
                return False
        except (TypeError, ValueError):
            pass
    if filters.created_before.strip():
        try:
            if note.created_at > datetime.fromisoformat(filters.created_before.strip()):
                return False
        except (TypeError, ValueError):
            pass
    if filters.parent_note_id.strip():
        parent_id = filters.parent_note_id.strip()
        if note.id != parent_id and note.chunk.parent_note_id != parent_id:
            return False
    return True


def note_is_current(note: KnowledgeNote) -> bool:
    return note.version.status == "current" and note.version.superseded_by_note_id is None


def active_version_sql() -> str:
    return (
        "AND coalesce(payload#>>'{version,status}', 'current') = 'current' "
        "AND coalesce(payload#>>'{version,superseded_by_note_id}', '') = ''"
    )
