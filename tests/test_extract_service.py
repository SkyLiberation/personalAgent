"""Unit tests for the lightweight pre-extraction layer.

These tests do NOT hit a live LLM. They:
  * exercise the schema coercion path on a hand-built fake LangExtract result
  * verify enable/disable + min-length gating
  * verify the fallback-on-error path swallows runtime exceptions
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from personal_agent.core.config import LangExtractConfig
from personal_agent.extract.schemas import SectionMap, SectionRecord
from personal_agent.extract.service import PreExtractError, PreExtractService


def _annotated(extractions: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(extractions=extractions)


def _ext(
    *,
    text: str,
    start: int,
    end: int,
    attributes: dict[str, Any],
) -> SimpleNamespace:
    return SimpleNamespace(
        extraction_class="section",
        extraction_text=text,
        attributes=attributes,
        char_interval=SimpleNamespace(start_pos=start, end_pos=end),
    )


def test_to_section_map_normalizes_attributes() -> None:
    annotated = _annotated(
        [
            _ext(
                text="Decision: pick checkpoint over store",
                start=0,
                end=37,
                attributes={
                    "topic": "Checkpoint vs Store",
                    "summary": "We pick checkpoint for short-term recovery.",
                    "contains_entities": ["checkpoint", " store ", ""],
                    "contains_relations": True,
                    "information_density": "HIGH",
                    "graph_worthy": True,
                    "reason": "decision recorded",
                },
            ),
            _ext(
                text="目录\n1. 引言",
                start=37,
                end=46,
                attributes={
                    "topic": "目录",
                    "graph_worthy": False,
                    "information_density": "weird-value",
                    "contains_entities": "single-string-entity",
                },
            ),
        ]
    )

    section_map = PreExtractService._to_section_map(annotated, "x" * 50)

    assert isinstance(section_map, SectionMap)
    assert len(section_map.sections) == 2
    first = section_map.sections[0]
    assert first.topic == "Checkpoint vs Store"
    assert first.contains_entities == ["checkpoint", "store"]
    assert first.information_density == "high"
    assert first.graph_worthy is True
    assert first.char_start == 0 and first.char_end == 37

    second = section_map.sections[1]
    assert second.graph_worthy is False
    assert second.information_density == "medium"  # coerced from invalid value
    assert second.contains_entities == ["single-string-entity"]

    assert section_map.graph_worthy_sections() == [first]
    assert section_map.doc_topic == "Checkpoint vs Store"


def test_should_run_respects_disabled_flag() -> None:
    cfg = LangExtractConfig(enabled=False, api_key="k", min_doc_chars=10)
    svc = PreExtractService(cfg)
    assert svc.should_run("x" * 100) is False


def test_should_run_respects_min_doc_chars() -> None:
    cfg = LangExtractConfig(enabled=True, api_key="k", min_doc_chars=50)
    svc = PreExtractService(cfg)
    assert svc.should_run("x" * 30) is False
    assert svc.should_run("x" * 60) is True


def test_should_run_requires_api_key() -> None:
    cfg = LangExtractConfig(enabled=True, api_key=None, min_doc_chars=10)
    svc = PreExtractService(cfg)
    assert svc.should_run("x" * 100) is False


def test_extract_returns_empty_when_disabled() -> None:
    cfg = LangExtractConfig(enabled=False, api_key="k")
    svc = PreExtractService(cfg)
    out = svc.extract("anything")
    assert isinstance(out, SectionMap)
    assert out.sections == []


def test_extract_falls_back_on_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = LangExtractConfig(
        enabled=True, api_key="k", min_doc_chars=10, fallback_on_error=True
    )
    svc = PreExtractService(cfg)

    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("simulated provider failure")

    monkeypatch.setattr("personal_agent.extract.service.run_extract", _boom)

    out = svc.extract("x" * 100)
    assert isinstance(out, SectionMap)
    assert out.sections == []


def test_extract_raises_when_fallback_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = LangExtractConfig(
        enabled=True, api_key="k", min_doc_chars=10, fallback_on_error=False
    )
    svc = PreExtractService(cfg)

    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("simulated provider failure")

    monkeypatch.setattr("personal_agent.extract.service.run_extract", _boom)

    with pytest.raises(PreExtractError):
        svc.extract("x" * 100)


def test_extract_calls_run_extract_with_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = LangExtractConfig(enabled=True, api_key="k", min_doc_chars=1)
    svc = PreExtractService(cfg)

    captured: dict[str, Any] = {}

    def _fake_run(text: str, **kwargs: Any) -> Any:
        captured["text"] = text
        captured.update(kwargs)
        return _annotated(
            [
                _ext(
                    text="hello",
                    start=0,
                    end=5,
                    attributes={"topic": "Hi", "graph_worthy": True},
                )
            ]
        )

    monkeypatch.setattr("personal_agent.extract.service.run_extract", _fake_run)

    out = svc.extract("hello world")
    assert out.sections[0].topic == "Hi"
    assert captured["text"] == "hello world"
    assert captured["config"] is cfg
    assert captured["prompt"]
    assert captured["examples"]


def test_section_record_defaults() -> None:
    rec = SectionRecord()
    assert rec.graph_worthy is False
    assert rec.information_density == "medium"
    assert rec.contains_entities == []
