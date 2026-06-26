"""Real LangExtract Research event-quality gate.

Unlike ``test_research_event_quality_gate.py``, this gate does not inject fixed
event frames. It runs the configured LangExtract endpoint and scores the actual
Research event-frame extraction behavior. Missing API config skips the test.
Provider extraction failures are kept inside the run by enabling the production
fallback path, so failures show up as lower quality metrics instead of aborting
the report before it can be compared.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from personal_agent.application.research import ResearchService
from personal_agent.application.research.extraction import (
    LangExtractResearchEventExtractor,
)
from personal_agent.kernel.config import Settings

from .dataset import (
    ResearchEventQualityRunOutput,
    default_event_quality_cases_path,
    load_event_quality_cases,
)
from .scorer import score_event_quality_all
from .test_research_event_quality_gate import (
    FixtureResearchTools,
    InMemoryResearchStore,
)


def test_real_langextract_research_event_quality_meets_baseline():
    settings = Settings.from_env()
    if not settings.langextract.api_key:
        pytest.skip("LangExtract API key is not configured.")

    config = settings.langextract.model_copy(update={"fallback_on_error": True})
    cases = load_event_quality_cases(default_event_quality_cases_path())
    runs: dict[str, ResearchEventQualityRunOutput] = {}

    for case in cases:
        store = InMemoryResearchStore()
        service = ResearchService(
            store,
            FixtureResearchTools(case),
            event_extractor=LangExtractResearchEventExtractor(config),
        )
        run = service.prepare_run(
            user_id=f"real-eval-{case.id}",
            topic=case.topic,
            instructions=case.instructions,
            max_items=case.max_items,
        )
        service.plan_queries(run.id)
        service.collect_sources(run.id)
        service.cluster_events(run.id)
        service.rank_events(run.id, max_items=case.max_items)
        completed = service.compose_digest(run.id, max_items=case.max_items)
        events = store.list_run_events(run.id)
        digest = store.get_digest(completed.digest_id or "")

        runs[case.id] = ResearchEventQualityRunOutput(
            source_count=completed.source_count,
            event_titles=[event.title for event in events],
            events=events,
            digest_titles=[
                item.title
                for item in (digest.items if digest is not None else [])
            ],
        )

    report = score_event_quality_all(cases, runs)
    baseline = json.loads(
        (Path(__file__).parent / "event_quality_real_baseline.json").read_text(
            encoding="utf-8"
        )
    )
    failures = report.check_thresholds(baseline)
    assert not failures, f"regression:\n{report.summary()}\nfailures={failures}"
