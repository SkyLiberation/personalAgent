from __future__ import annotations

from types import SimpleNamespace

from personal_agent.application.research.extraction import (
    LangExtractResearchEventExtractor,
    ResearchEventFrame,
    frames_describe_same_event,
)
from personal_agent.application.research.models import ResearchSource


def _source() -> ResearchSource:
    return ResearchSource(
        url="https://openai.com/news/agent-runtime-sdk",
        canonical_url="https://openai.com/news/agent-runtime-sdk",
        domain="openai.com",
        title="OpenAI launches Agent Runtime SDK",
        snippet="OpenAI launches an SDK for agent runtime orchestration.",
        source_type="official",
    )


def test_event_frames_merge_semantic_title_rewrites():
    left = ResearchEventFrame(
        source_url="https://openai.com/news/agent-runtime-sdk",
        title="OpenAI launches Agent Runtime SDK",
        actor="OpenAI",
        action="release",
        object="Agent Runtime SDK",
        event_type="product_release",
    )
    right = ResearchEventFrame(
        source_url="https://news.example/openai-runtime-sdk",
        title="New runtime SDK for AI agents announced by OpenAI",
        actor="OpenAI",
        action="announce",
        object="Agent Runtime SDK",
        event_type="product_release",
    )

    assert frames_describe_same_event(left, right)


def test_event_frames_merge_equivalent_product_event_types():
    release = ResearchEventFrame(
        source_url="https://openai.com/news/agent-runtime-sdk",
        title="OpenAI launches Agent Runtime SDK",
        actor="OpenAI",
        action="release",
        object="Agent Runtime SDK",
        event_type="product_release",
    )
    announcement = ResearchEventFrame(
        source_url="https://news.example/openai-runtime-sdk",
        title="New runtime SDK for AI agents announced by OpenAI",
        actor="OpenAI",
        action="announce",
        object="runtime SDK for AI agents",
        event_type="product_announcement",
    )

    assert frames_describe_same_event(release, announcement)


def test_event_frames_keep_similar_but_different_events_apart():
    release = ResearchEventFrame(
        source_url="https://openai.com/news/agent-runtime-sdk",
        title="OpenAI launches Agent Runtime SDK",
        actor="OpenAI",
        action="release",
        object="Agent Runtime SDK",
        event_type="product_release",
    )
    patch = ResearchEventFrame(
        source_url="https://news.example/openai-runtime-sdk-security",
        title="OpenAI patches Agent Runtime SDK security issue",
        actor="OpenAI",
        action="patch",
        object="Agent Runtime SDK security issue",
        event_type="security_update",
    )

    assert not frames_describe_same_event(release, patch)


def test_langextract_research_event_output_maps_to_frame():
    annotated = SimpleNamespace(
        extractions=[
            SimpleNamespace(
                extraction_class="research_event",
                attributes={
                    "actor": "OpenAI",
                    "action": "release",
                    "object": "Agent Runtime SDK",
                    "event_type": "product_release",
                    "occurred_at": "2026-06-26",
                    "entities": ["OpenAI", "Agent Runtime SDK"],
                    "confidence": 0.91,
                },
            )
        ]
    )

    frame = LangExtractResearchEventExtractor._to_frame(annotated, _source())

    assert frame.actor == "OpenAI"
    assert frame.action == "release"
    assert frame.object == "Agent Runtime SDK"
    assert frame.event_type == "product_release"
    assert frame.confidence == 0.91
