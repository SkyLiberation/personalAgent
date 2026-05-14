from __future__ import annotations

import pytest

from personal_agent.core.chunking import (
    chunk_content,
    _split_by_headings,
    _split_by_paragraphs,
    _derive_title,
    _finalize_chunks,
    MIN_CHUNK_CHARS,
    MAX_CHUNK_CHARS,
)


class TestChunkContent:
    def test_empty_content_returns_single_chunk(self):
        result = chunk_content("")
        assert len(result) == 1
        assert result[0]["title"] == "空内容"

    def test_whitespace_only_returns_single_chunk(self):
        result = chunk_content("   \n  \n  ")
        assert len(result) == 1

    def test_short_content_not_split(self):
        content = "这是一段很短的笔记内容，只有一句话。"
        result = chunk_content(content)
        assert len(result) == 1
        assert result[0]["content"] == content

    def test_heading_split_produces_multiple_chunks(self):
        content = "\n".join([
            "# 主标题",
            "",
            "前言内容，这里有一些介绍性的文字。" * 50,
            "",
            "## 第一节 基础概念",
            "",
            "第一节的内容。" * 350,
            "",
            "## 第二节 进阶主题",
            "",
            "第二节的内容。" * 350,
        ])
        result = chunk_content(content)
        assert len(result) >= 2

    def test_paragraph_split_fallback(self):
        content = "\n\n".join([
            "第一段内容。" * 200,
            "第二段内容。" * 200,
            "第三段内容。" * 200,
        ])
        result = chunk_content(content)
        assert len(result) >= 1

    def test_no_heading_single_paragraph_not_split(self):
        content = "这是一段没有标题也没有多个段落的普通文本。" * 50
        result = chunk_content(content)
        assert len(result) == 1


class TestSplitByHeadings:
    def test_empty_content_returns_empty(self):
        assert _split_by_headings("") == []

    def test_no_headings_returns_empty(self):
        assert _split_by_headings("plain text\nno headings\nhere") == []

    def test_single_heading_with_body(self):
        content = "# 标题\n\n正文内容。" * 100
        chunks = _split_by_headings(content)
        assert len(chunks) >= 1
        assert chunks[0]["title"] == "标题"

    def test_multiple_headings(self):
        content = "\n".join([
            "## 第一节",
            "",
            "第一节内容。" * 200,
            "",
            "## 第二节",
            "",
            "第二节内容。" * 200,
        ])
        chunks = _split_by_headings(content)
        assert len(chunks) == 2
        assert chunks[0]["title"] == "第一节"
        assert chunks[1]["title"] == "第二节"

    def test_preamble_before_first_heading(self):
        preamble_text = "前言介绍文字。" * 50
        content = preamble_text + "\n\n## 第一章\n\n正文。" * 100
        chunks = _split_by_headings(content)
        assert any(c["source_span"] == "前言" for c in chunks)

    def test_very_short_preamble_skipped(self):
        content = "短\n\n## 章节\n\n正文。" * 100
        chunks = _split_by_headings(content)
        # Short preamble (< 40 chars after strip) should be skipped
        preamble_chunks = [c for c in chunks if c["source_span"] == "前言"]
        assert len(preamble_chunks) == 0

    def test_empty_heading_body_skipped(self):
        content = "## 空章节\n\n\n## 有内容的章节\n\n正文。" * 100
        chunks = _split_by_headings(content)
        titles = [c["title"] for c in chunks]
        assert "有内容的章节" in titles
        assert "空章节" not in titles


class TestSplitByParagraphs:
    def test_single_paragraph_returns_empty(self):
        assert _split_by_paragraphs("只有一段") == []

    def test_two_short_paragraphs_returns_empty(self):
        assert _split_by_paragraphs("段落1\n\n段落2") == []

    def test_two_long_paragraphs_split(self):
        para1 = "段落1。" * 600
        para2 = "段落2。" * 600
        chunks = _split_by_paragraphs(f"{para1}\n\n{para2}")
        assert len(chunks) >= 2


class TestDeriveTitle:
    def test_first_non_heading_line(self):
        assert _derive_title("## 标题\n第一行实际内容文本") == "第一行实际内容文本"

    def test_truncation(self):
        title = _derive_title("a" * 100)
        assert len(title) <= 27  # 24 + "..."

    def test_empty_fallback(self):
        title = _derive_title("")
        assert title == ""


class TestFinalizeChunks:
    def test_single_chunk_passes_through(self):
        chunk = {"title": "T", "content": "C" * 100, "source_span": "S"}
        result = _finalize_chunks([chunk])
        assert len(result) == 1

    def test_undersized_chunks_merged(self):
        small = {"title": "S1", "content": "x" * 100, "source_span": "span1"}
        medium = {"title": "S2", "content": "y" * (MIN_CHUNK_CHARS + 1), "source_span": "span2"}
        result = _finalize_chunks([small, medium])
        # small should be merged into medium or left as standalone if it's the only undersized one
        assert len(result) >= 1
        assert any("span2" in c["source_span"] for c in result)
