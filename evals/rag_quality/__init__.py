"""Offline RAG-quality evaluation harness (Layer 4).

A fixed annotated Q&A dataset scored across three metric families — retrieval,
generation, grounding — and wired as a regression gate. The scoring logic is
pure-function and dependency-free (no DB, no LLM), so the gate test is fully
hermetic; only the optional CLI runner drives the real ``execute_ask`` pipeline.

Reuses the IR primitives already in ``evals/open_ragbench/metrics.py`` rather
than reimplementing recall@k / nDCG@k.
"""
