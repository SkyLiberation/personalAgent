from __future__ import annotations

from personal_agent.agent.provenance import HeuristicProvenanceExtractor
from personal_agent.core.models import RawIngestItem


def _item(content="", source_type="text", source_ref=None, metadata=None) -> RawIngestItem:
    return RawIngestItem(
        content=content,
        source_type=source_type,
        source_ref=source_ref,
        metadata=metadata or {},
    )


class TestHeuristicProvenanceExtractor:
    def test_author_and_date_from_metadata(self):
        prov = HeuristicProvenanceExtractor().extract(
            _item(metadata={"author": "Jane Doe", "published_at": "2025-03-01"})
        )
        assert prov.author == "Jane Doe"
        assert prov.published_at == "2025-03-01"

    def test_doc_type_from_filename_extension(self):
        prov = HeuristicProvenanceExtractor().extract(
            _item(source_type="file", source_ref="/uploads/report.pdf")
        )
        assert prov.doc_type == "pdf"

    def test_doc_type_falls_back_to_source_type(self):
        prov = HeuristicProvenanceExtractor().extract(_item(source_type="link"))
        assert prov.doc_type == "web"

    def test_date_scanned_from_content(self):
        prov = HeuristicProvenanceExtractor().extract(_item(content="发布于 2024/12/5 的公告"))
        assert prov.published_at == "2024-12-05"

    def test_language_detection(self):
        ext = HeuristicProvenanceExtractor()
        assert ext.extract(_item(content="这是一段中文内容用于测试语言判断。")).language == "zh"
        assert ext.extract(_item(content="This is an English sentence for detection.")).language == "en"

    def test_empty_content_yields_no_language(self):
        assert HeuristicProvenanceExtractor().extract(_item(content="   ")).language is None
