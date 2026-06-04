"""Download and parse the MultiHopRAG dataset from HuggingFace.

Dataset: ``yixuantt/MultiHopRAG`` (COLM 2024). Two JSON files at repo root:

- ``corpus.json``: news articles ``{title, author, source, published_at,
  category, url, body}`` (no section split — body is the full article).
- ``MultiHopRAG.json``: queries ``{query, answer, question_type,
  evidence_list}`` where each evidence is ``{title, author, url, source,
  category, published_at, fact}``.

Documents have no explicit id, so the article ``url`` is used as the unique
doc key. Queries have no id either, so a deterministic ``mhr_{index}`` id is
assigned after a stable sort.
"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from huggingface_hub import snapshot_download

logger = logging.getLogger(__name__)

_DATASET_REPO = "yixuantt/MultiHopRAG"
CorpusMode = Literal["relevant", "full"]


@dataclass(frozen=True)
class MHRDoc:
    doc_id: str  # the article URL (unique)
    title: str
    source: str
    published_at: str
    category: str
    body: str


@dataclass(frozen=True)
class MHRQuery:
    query_id: str
    query_text: str
    question_type: str  # inference_query | comparison_query | temporal_query | null_query
    answer: str
    evidence_urls: tuple[str, ...] = field(default_factory=tuple)


def ensure_dataset(cache_dir: Path | None = None) -> Path:
    """Download the dataset from HuggingFace if not already cached.

    Returns the path to the snapshot directory containing ``corpus.json`` and
    ``MultiHopRAG.json``.
    """
    if cache_dir is None:
        cache_dir = Path(__file__).resolve().parents[2] / "data" / "huggingface"
    root = snapshot_download(
        _DATASET_REPO,
        repo_type="dataset",
        allow_patterns=["*.json"],
        cache_dir=cache_dir,
    )
    data_dir = Path(root)
    if not (data_dir / "MultiHopRAG.json").exists():
        raise FileNotFoundError(f"MultiHopRAG.json not found in: {data_dir}")
    if not (data_dir / "corpus.json").exists():
        raise FileNotFoundError(f"corpus.json not found in: {data_dir}")
    logger.info("MultiHopRAG data dir: %s", data_dir)
    return data_dir


def load_queries(data_dir: Path) -> list[MHRQuery]:
    """Parse MultiHopRAG.json into MHRQuery objects with stable ids."""
    raw = json.loads((data_dir / "MultiHopRAG.json").read_text(encoding="utf-8"))
    queries: list[MHRQuery] = []
    for index, item in enumerate(raw):
        evidence = item.get("evidence_list") or []
        # Preserve first-seen order while de-duplicating evidence URLs.
        seen: set[str] = set()
        urls: list[str] = []
        for ev in evidence:
            url = (ev.get("url") or "").strip()
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        queries.append(MHRQuery(
            query_id=f"mhr_{index:05d}",
            query_text=item["query"],
            question_type=item.get("question_type", "unknown"),
            answer=str(item.get("answer", "")),
            evidence_urls=tuple(urls),
        ))
    logger.info("Loaded %d MultiHopRAG queries", len(queries))
    return queries


def load_corpus(data_dir: Path, doc_ids: set[str] | None = None) -> dict[str, MHRDoc]:
    """Load corpus.json, optionally filtering to specific doc URLs."""
    raw = json.loads((data_dir / "corpus.json").read_text(encoding="utf-8"))
    docs: dict[str, MHRDoc] = {}
    for item in raw:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        if doc_ids is not None and url not in doc_ids:
            continue
        body = (item.get("body") or "").strip()
        if not body:
            continue
        docs[url] = MHRDoc(
            doc_id=url,
            title=item.get("title", ""),
            source=item.get("source", ""),
            published_at=item.get("published_at", ""),
            category=item.get("category", ""),
            body=body,
        )
    logger.info("Loaded %d corpus docs", len(docs))
    return docs


def load_benchmark(
    num_queries: int | None = None,
    seed: int = 42,
    cache_dir: Path | None = None,
    corpus_mode: CorpusMode = "relevant",
) -> tuple[list[MHRQuery], dict[str, MHRDoc]]:
    """High-level entry: download, parse, optionally subsample.

    Returns ``(queries, corpus_docs)``. When *num_queries* is given a
    deterministic random sample of that size is returned.

    ``corpus_mode="relevant"`` loads only the documents referenced by the
    sampled queries' evidence URLs — fast, but understates retrieval difficulty
    because there are fewer distractor documents. ``corpus_mode="full"`` loads
    the whole corpus and is the fairer setting for retrieval comparisons.
    """
    if corpus_mode not in {"relevant", "full"}:
        raise ValueError("corpus_mode must be 'relevant' or 'full'")

    data_dir = ensure_dataset(cache_dir)
    all_queries = load_queries(data_dir)
    all_queries.sort(key=lambda q: q.query_id)

    if num_queries is not None and num_queries < len(all_queries):
        rng = random.Random(seed)
        all_queries = sorted(rng.sample(all_queries, num_queries), key=lambda q: q.query_id)

    if corpus_mode == "relevant":
        doc_ids: set[str] | None = set()
        for query in all_queries:
            doc_ids.update(query.evidence_urls)
    else:
        doc_ids = None
    corpus = load_corpus(data_dir, doc_ids)
    return all_queries, corpus
