"""MultiHopRAG benchmark evaluation helpers.

Wraps the ``yixuantt/MultiHopRAG`` dataset (COLM 2024) for multi-hop retrieval
evaluation. Unlike Open RAGBench (single-hop, one relevant doc per query),
MultiHopRAG queries draw evidence from 2-4 distinct documents and come in four
difficulty types (inference / comparison / temporal / null), so relevance is a
*set* of documents and metrics are additionally grouped by question type.
"""
