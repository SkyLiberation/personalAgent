from __future__ import annotations

from personal_agent.core.evidence import EvidenceItem, compress_evidence


def _note(snippet: str, source_type: str = "note") -> EvidenceItem:
    return EvidenceItem(source_type=source_type, source_id="n1", title="t", snippet=snippet)


class TestCompressEvidence:
    def test_keeps_question_relevant_sentences(self):
        snippet = (
            "The weather was pleasant that sunny morning when we arrived at the office. "
            "Redis caches hot order data in memory to cut database load significantly. "
            "Lunch was served at noon in the downstairs cafeteria as usual. "
            "The cache eviction policy uses LRU for order keys under memory pressure. "
            "Someone mentioned the parking lot was completely full again today."
        )
        item = _note(snippet)
        out = compress_evidence("redis cache order data", [item], max_sentences=2)[0]
        assert "Redis caches hot order data" in out.snippet
        assert "weather" not in out.snippet
        assert out.metadata["compressed_from_chars"] == len(snippet)

    def test_preserves_original_order(self):
        snippet = (
            "The cache layer absorbs read traffic for incoming order requests every second. "
            "This is a filler sentence with absolutely no relevant signal in it whatsoever here. "
            "Order data is sharded across multiple cache nodes for horizontal scalability and speed."
        )
        out = compress_evidence("cache order data", [_note(snippet)], max_sentences=2)[0]
        i_first = out.snippet.index("absorbs read traffic")
        i_second = out.snippet.index("sharded across")
        assert i_first < i_second

    def test_short_snippet_untouched(self):
        item = _note("Short note about orders.")
        out = compress_evidence("orders", [item], max_sentences=2)[0]
        assert out.snippet == "Short note about orders."
        assert "compressed_from_chars" not in out.metadata

    def test_graph_fact_untouched(self):
        long_fact = "Redis caches order data. " * 20
        item = _note(long_fact, source_type="graph_fact")
        out = compress_evidence("redis order", [item], max_sentences=2)[0]
        assert out.snippet == long_fact

    def test_no_overlap_keeps_original(self):
        snippet = (
            "Alpha beta gamma delta epsilon zeta. Eta theta iota kappa lambda mu. "
            "Nu xi omicron pi rho sigma. Tau upsilon phi chi psi omega here. "
            "Aleph bet gimel dalet he vav zayin chet tet."
        )
        out = compress_evidence("completely unrelated query terms", [_note(snippet)], max_sentences=2)[0]
        assert out.snippet == snippet
