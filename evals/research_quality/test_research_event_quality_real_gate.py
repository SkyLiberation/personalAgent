"""Real structured-LLM Research event-quality gate.

Unlike ``test_research_event_quality_gate.py``, this gate does not inject fixed
event frames. It runs the configured structured LLM endpoint and scores the actual
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
    StructuredResearchEventExtractor,
)
from personal_agent.kernel.config import Settings

from .dataset import (
    ResearchEventQualityRunOutput,
    build_research_event_quality_run_output,
    default_event_quality_cases_path,
    load_event_quality_cases,
)
from .scorer import score_event_quality_all
from .test_research_event_quality_gate import (
    FixtureResearchTools,
    InMemoryResearchStore,
    fixture_generate_text,
)


def test_real_structured_llm_research_event_quality_meets_baseline():
    settings = Settings.from_env()
    if not settings.langextract.api_key:
        pytest.skip("Structured extraction API key is not configured.")

    config = settings.langextract.model_copy(update={"fallback_on_error": True})
    cases = load_event_quality_cases(default_event_quality_cases_path())
    runs: dict[str, ResearchEventQualityRunOutput] = {}

    for case in cases:
        store = InMemoryResearchStore()
        service = ResearchService(
            store,
            FixtureResearchTools(case),
            generate_text=fixture_generate_text(case),
            event_extractor=StructuredResearchEventExtractor(config),
        )
        run = service.prepare_run(
            user_id=f"real-eval-{case.id}",
            topic=case.topic,
            instructions=case.instructions,
            max_items=case.max_items,
        )
        service.initialize_state(run.id)
        state = service.run_research_loop(run.id)
        completed = service.synthesize_digest(run.id, max_items=case.max_items)
        digest = service.verify_digest(run.id)
        sources = store.list_run_sources(run.id)
        events = store.list_run_events(run.id)
        digest = digest or store.get_digest(completed.digest_id or "")

        runs[case.id] = build_research_event_quality_run_output(
            completed=completed,
            state=state,
            sources=sources,
            events=events,
            digest=digest,
        )

    report = score_event_quality_all(cases, runs)
    baseline = json.loads(
        (Path(__file__).parent / "event_quality_real_baseline.json").read_text(
            encoding="utf-8"
        )
    )
    failures = report.check_thresholds(baseline)
    assert not failures, f"regression:\n{report.summary()}\nfailures={failures}"
