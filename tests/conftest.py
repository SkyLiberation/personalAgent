from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from personal_agent.core.config import Settings
from personal_agent.core.models import Citation, KnowledgeNote


@pytest.fixture
def temp_dir() -> Path:
    """Temp directory fixture that works with pytest-asyncio strict mode on Windows."""
    path = Path(tempfile.mkdtemp(prefix="pytest-"))
    yield path
    try:
        shutil.rmtree(path)
    except Exception:
        pass


@pytest.fixture
def settings() -> Settings:
    return Settings(
        data_dir="./data",
        openai_api_key="sk-test-key",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        openai_small_model="gpt-4.1-nano",
    )


@pytest.fixture
def sample_note_factory():
    def _make(
        note_id: str = "note-001",
        title: str = "测试笔记",
        content: str = "这是一篇关于Python单元测试的笔记。",
        summary: str = "Python单元测试入门",
        tags: list[str] | None = None,
    ) -> KnowledgeNote:
        return KnowledgeNote(
            id=note_id,
            title=title,
            content=content,
            summary=summary,
            tags=tags or ["python", "测试"],
        )

    return _make


@pytest.fixture
def sample_note(sample_note_factory) -> KnowledgeNote:
    return sample_note_factory()


@pytest.fixture
def sample_citation_factory():
    def _make(
        note_id: str = "note-001",
        title: str = "测试笔记",
        snippet: str = "Python单元测试...",
        relation_fact: str | None = None,
    ) -> Citation:
        return Citation(
            note_id=note_id,
            title=title,
            snippet=snippet,
            relation_fact=relation_fact,
        )

    return _make


@pytest.fixture
def sample_citation(sample_citation_factory) -> Citation:
    return sample_citation_factory()
