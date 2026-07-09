"""Load Galileo RAGBench parquet splits from HuggingFace.

The Galileo dataset is shaped differently from Open RAGBench: every row already
contains the candidate documents and sentence-level support/utilization labels.
This loader keeps that shape explicit so eval strategies can operate at the
sentence evidence level instead of assuming paper parent/section structure.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pandas as pd
from huggingface_hub import hf_hub_download

Split = Literal["train", "validation", "test"]
RelevanceMode = Literal["relevant", "utilized"]

_DATASET_REPO = "galileo-ai/ragbench"


@dataclass(frozen=True)
class GalileoSentence:
    key: str
    text: str
    document_index: int


@dataclass(frozen=True)
class GalileoExample:
    query_id: str
    question: str
    dataset_name: str
    subset: str
    split: Split
    documents: tuple[str, ...]
    sentences: tuple[GalileoSentence, ...]
    relevant_sentence_keys: tuple[str, ...] = field(default_factory=tuple)
    utilized_sentence_keys: tuple[str, ...] = field(default_factory=tuple)
    response: str = ""
    adherence_score: bool | None = None
    relevance_score: float | None = None
    utilization_score: float | None = None
    completeness_score: float | None = None


def ensure_split(
    *,
    subset: str = "covidqa",
    split: Split = "test",
    cache_dir: Path | None = None,
) -> Path:
    filename = f"{subset}/{split}-00000-of-00001.parquet"
    path = hf_hub_download(
        _DATASET_REPO,
        filename,
        repo_type="dataset",
        cache_dir=cache_dir,
    )
    return Path(path)


def load_examples(
    *,
    subset: str = "covidqa",
    split: Split = "test",
    num_queries: int | None = None,
    seed: int = 13,
    cache_dir: Path | None = None,
) -> list[GalileoExample]:
    path = ensure_split(subset=subset, split=split, cache_dir=cache_dir)
    frame = pd.read_parquet(path)
    examples = [_row_to_example(row, subset=subset, split=split) for row in frame.to_dict("records")]
    examples.sort(key=lambda item: item.query_id)
    if num_queries is not None and num_queries < len(examples):
        rng = random.Random(seed)
        examples = sorted(rng.sample(examples, num_queries), key=lambda item: item.query_id)
    return examples


def _row_to_example(row: dict, *, subset: str, split: Split) -> GalileoExample:
    raw_id = str(row.get("id") or "")
    dataset_name = str(row.get("dataset_name") or f"{subset}_{split}")
    query_id = f"{subset}_{split}_{raw_id}"
    documents = tuple(str(item) for item in _as_list(row.get("documents")) if str(item).strip())
    sentences = tuple(_sentences_from_documents(row.get("documents_sentences")))
    return GalileoExample(
        query_id=query_id,
        question=str(row.get("question") or ""),
        dataset_name=dataset_name,
        subset=subset,
        split=split,
        documents=documents,
        sentences=sentences,
        relevant_sentence_keys=tuple(str(item) for item in _as_list(row.get("all_relevant_sentence_keys"))),
        utilized_sentence_keys=tuple(str(item) for item in _as_list(row.get("all_utilized_sentence_keys"))),
        response=str(row.get("response") or ""),
        adherence_score=_optional_bool(row.get("adherence_score")),
        relevance_score=_optional_float(row.get("relevance_score")),
        utilization_score=_optional_float(row.get("utilization_score")),
        completeness_score=_optional_float(row.get("completeness_score")),
    )


def _sentences_from_documents(value: object) -> list[GalileoSentence]:
    sentences: list[GalileoSentence] = []
    for doc_index, raw_doc in enumerate(_as_list(value)):
        for raw_sentence in _as_list(raw_doc):
            parts = _as_list(raw_sentence)
            if len(parts) < 2:
                continue
            key = str(parts[0])
            text = str(parts[1]).strip()
            if key and text:
                sentences.append(GalileoSentence(key=key, text=text, document_index=doc_index))
    return sentences


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "tolist"):
        converted = value.tolist()
        return converted if isinstance(converted, list) else [converted]
    return [value]


def _optional_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    return None
