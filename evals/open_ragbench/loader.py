"""Download and parse the Open RAG Benchmark dataset from HuggingFace."""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from huggingface_hub import snapshot_download

logger = logging.getLogger(__name__)

_DATASET_REPO = "vectara/open_ragbench"
_DATA_SUBDIR = "pdf/arxiv"
CorpusMode = Literal["relevant", "full"]


@dataclass(frozen=True)
class RAGBenchQuery:
    query_id: str
    query_text: str
    query_type: str  # "abstractive" or "extractive"
    relevant_doc_id: str
    relevant_section_idx: int
    answer: str


@dataclass(frozen=True)
class RAGBenchDoc:
    doc_id: str
    title: str
    abstract: str
    sections: list[str]


def ensure_dataset(cache_dir: Path | None = None) -> Path:
    """Download the dataset from HuggingFace if not already cached.

    Returns the path to the ``official/pdf/arxiv/`` directory.
    """
    root = snapshot_download(
        _DATASET_REPO,
        repo_type="dataset",
        allow_patterns=[f"{_DATA_SUBDIR}/*"],
        cache_dir=cache_dir,
    )
    data_dir = Path(root) / _DATA_SUBDIR
    if not data_dir.exists():
        raise FileNotFoundError(f"Dataset directory not found: {data_dir}")
    logger.info("Open RAG Benchmark data dir: %s", data_dir)
    return data_dir


def load_queries(data_dir: Path) -> list[RAGBenchQuery]:
    """Parse queries.json + qrels.json + answers.json, filter to text-only."""
    queries_raw = json.loads((data_dir / "queries.json").read_text(encoding="utf-8"))
    qrels_raw = json.loads((data_dir / "qrels.json").read_text(encoding="utf-8"))
    answers_raw = json.loads((data_dir / "answers.json").read_text(encoding="utf-8"))

    queries: list[RAGBenchQuery] = []
    for qid, meta in queries_raw.items():
        if meta.get("source") != "text":
            continue
        qrel = qrels_raw.get(qid)
        if not qrel:
            continue
        answer = answers_raw.get(qid)
        if answer is None:
            continue
        queries.append(RAGBenchQuery(
            query_id=qid,
            query_text=meta["query"],
            query_type=meta.get("type", "unknown"),
            relevant_doc_id=qrel["doc_id"],
            relevant_section_idx=qrel["section_id"],
            answer=answer,
        ))
    queries.sort(key=lambda q: q.query_id)
    logger.info("Loaded %d text-source queries", len(queries))
    return queries


def load_corpus(data_dir: Path, doc_ids: set[str] | None = None) -> dict[str, RAGBenchDoc]:
    """Load corpus/*.json files, optionally filtering to specific doc IDs."""
    corpus_dir = data_dir / "corpus"
    docs: dict[str, RAGBenchDoc] = {}
    for path in sorted(corpus_dir.glob("*.json")):
        doc_id = path.stem
        if doc_ids is not None and doc_id not in doc_ids:
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        sections: list[str] = []
        for sec in raw.get("sections", []):
            text = sec.get("text", "").strip()
            if text:
                sections.append(text)
        docs[doc_id] = RAGBenchDoc(
            doc_id=doc_id,
            title=raw.get("title", ""),
            abstract=raw.get("abstract", ""),
            sections=sections,
        )
    logger.info("Loaded %d corpus docs", len(docs))
    return docs


def load_benchmark(
    num_queries: int | None = None,
    seed: int = 42,
    cache_dir: Path | None = None,
    corpus_mode: CorpusMode = "relevant",
) -> tuple[list[RAGBenchQuery], dict[str, RAGBenchDoc]]:
    """High-level entry: download, parse, optionally subsample.

    Returns (queries, corpus_docs).  When *num_queries* is given a
    deterministic random sample of that size is returned.

    ``corpus_mode="relevant"`` keeps benchmark iterations fast by loading only
    documents referenced by the sampled queries. ``corpus_mode="full"`` loads
    the whole arxiv corpus split and is the fairer setting for retrieval
    comparisons because it includes unrelated candidate documents.
    """
    if corpus_mode not in {"relevant", "full"}:
        raise ValueError("corpus_mode must be 'relevant' or 'full'")

    data_dir = ensure_dataset(cache_dir)
    all_queries = load_queries(data_dir)

    if num_queries is not None and num_queries < len(all_queries):
        rng = random.Random(seed)
        all_queries = sorted(rng.sample(all_queries, num_queries), key=lambda q: q.query_id)

    doc_ids = None if corpus_mode == "full" else {q.relevant_doc_id for q in all_queries}
    corpus = load_corpus(data_dir, doc_ids)
    return all_queries, corpus
