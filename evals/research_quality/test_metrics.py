from personal_agent.application.research import ResearchEvent
from personal_agent.application.research.models import ResearchSource

from .metrics import score_research_events


def test_research_quality_metrics_reward_supported_deduplicated_events():
    event = ResearchEvent(
        canonical_key="release-1",
        title="Model release",
        summary="A model was released.",
        status="verified",
        sources=[
            ResearchSource(
                url="https://vendor.example/release",
                canonical_url="https://vendor.example/release",
                domain="vendor.example",
                title="Release",
                source_type="official",
            ),
            ResearchSource(
                url="https://news.example/report",
                canonical_url="https://news.example/report",
                domain="news.example",
                title="Report",
                source_type="media",
            ),
        ],
    )

    metrics = score_research_events([event], expected_keys={"release-1"})

    assert metrics.event_recall == 1
    assert metrics.event_precision == 1
    assert metrics.primary_source_rate == 1
    assert metrics.score == 1

