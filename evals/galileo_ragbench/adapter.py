"""Convert Galileo RAGBench rows into KnowledgeNote evidence units."""
from __future__ import annotations

import re

from personal_agent.kernel.models import KnowledgeNote, NoteBody, NoteChunk, NoteSource

from .loader import GalileoExample, RelevanceMode

_EVAL_USER = "galileo_ragbench_eval"


def corpus_to_notes(examples: list[GalileoExample]) -> list[KnowledgeNote]:
    notes: list[KnowledgeNote] = []
    seen: set[str] = set()
    for example in examples:
        for doc_index, document in enumerate(example.documents):
            parent_id = document_note_id(example.query_id, doc_index)
            if parent_id not in seen:
                seen.add(parent_id)
                notes.append(KnowledgeNote(
                    id=parent_id,
                    user_id=_EVAL_USER,
                    source=NoteSource(type="text"),
                    body=NoteBody(
                        title=f"{example.dataset_name} document {doc_index}",
                        content=document,
                        summary=document[:240],
                    ),
                ))
        for sentence in example.sentences:
            note_id = sentence_note_id(example.query_id, sentence.key)
            if note_id in seen:
                continue
            seen.add(note_id)
            parent_id = document_note_id(example.query_id, sentence.document_index)
            notes.append(KnowledgeNote(
                id=note_id,
                user_id=_EVAL_USER,
                source=NoteSource(type="text"),
                body=NoteBody(
                    title=f"{example.dataset_name} sentence {sentence.key}",
                    content=sentence.text,
                    summary=sentence.text[:240],
                ),
                chunk=NoteChunk(parent_note_id=parent_id, index=_sentence_key_index(sentence.key)),
            ))
    return notes


def relevance_by_query(
    examples: list[GalileoExample],
    *,
    mode: RelevanceMode = "relevant",
) -> dict[str, set[str]]:
    relevance: dict[str, set[str]] = {}
    for example in examples:
        keys = (
            example.utilized_sentence_keys
            if mode == "utilized"
            else example.relevant_sentence_keys
        )
        relevance[example.query_id] = {
            sentence_note_id(example.query_id, key)
            for key in keys
        }
    return relevance


def document_note_id(query_id: str, document_index: int) -> str:
    return f"galileo_{_safe_id(query_id)}_doc_{document_index}"


def sentence_note_id(query_id: str, sentence_key: str) -> str:
    return f"galileo_{_safe_id(query_id)}_sent_{_safe_id(sentence_key)}"


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    return cleaned.strip("_") or "empty"


def _sentence_key_index(key: str) -> int:
    match = re.search(r"(\d+)", key)
    return int(match.group(1)) if match else 0
