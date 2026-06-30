from __future__ import annotations

import json
from types import SimpleNamespace

from personal_agent.application.research.extraction import (
    LangExtractResearchEventExtractor,
    ResearchEventFrame,
    StructuredResearchEventExtractor,
    frames_describe_same_event,
)
from personal_agent.infra.structured_model import StructuredModelResponse
from personal_agent.kernel.config_models import LangExtractConfig
from personal_agent.application.research.models import ResearchSource


class _FakeStructuredClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        payload = json.loads(request.messages[-1]["content"])
        frames = [
            {
                "source_url": source["source_url"],
                "actor": "OpenAI",
                "action": "release",
                "object": "Agent Runtime SDK",
                "event_type": "product_release",
                "occurred_at": "2026-06-26",
                "entities": ["OpenAI", "Agent Runtime SDK"],
                "confidence": 0.91,
            }
            for source in payload["sources"]
        ]
        return StructuredModelResponse(
            value=request.output_type(),
            model="fake",
            latency_ms=1,
            content=json.dumps({"frames": frames}),
        )


def _source(
    *,
    title: str = "OpenAI launches Agent Runtime SDK",
    url: str = "https://openai.com/news/agent-runtime-sdk",
) -> ResearchSource:
    return ResearchSource(
        url=url,
        canonical_url=url,
        domain="openai.com" if "openai.com" in url else "news.example",
        title=title,
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


def test_structured_event_extractor_skips_model_for_single_source():
    client = _FakeStructuredClient()
    extractor = StructuredResearchEventExtractor(
        LangExtractConfig(api_key="k", base_url="https://example.test", model_id="fake"),
        model_client=client,
    )

    frames = extractor.extract([_source()], topic="Agent Runtime SDK")

    assert client.calls == 0
    assert frames["https://openai.com/news/agent-runtime-sdk"].confidence == 0.45


def test_structured_event_extractor_calls_model_for_semantic_rewrite_pair():
    client = _FakeStructuredClient()
    extractor = StructuredResearchEventExtractor(
        LangExtractConfig(api_key="k", base_url="https://example.test", model_id="fake"),
        model_client=client,
    )
    sources = [
        _source(),
        _source(
            title="New runtime SDK for AI agents announced by OpenAI",
            url="https://news.example/openai-runtime-sdk",
        ),
    ]

    frames = extractor.extract(sources, topic="Agent Runtime SDK")

    assert client.calls == 1
    assert frames["https://news.example/openai-runtime-sdk"].object == "Agent Runtime SDK"
    assert frames["https://news.example/openai-runtime-sdk"].confidence == 0.91

    frames = extractor.extract(sources, topic="Agent Runtime SDK")

    assert client.calls == 1
    assert frames["https://news.example/openai-runtime-sdk"].object == "Agent Runtime SDK"
