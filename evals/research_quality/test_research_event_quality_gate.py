"""Deterministic Research content-quality gate.

This gate runs the real ResearchService pipeline over fixed tool outputs. It
does not access live web/LLM services, but it evaluates the actual current
research algorithms: URL canonicalization, source collection, event clustering,
confidence calibration, personal relevance ranking and digest selection.
"""

from __future__ import annotations

import json
from pathlib import Path

from personal_agent.application.research import ResearchService
from personal_agent.application.research.models import (
    IntelligenceDigest,
    ResearchEvent,
    ResearchRun,
    ResearchSource,
    ResearchSubscription,
)
from personal_agent.application.research.extraction import (
    HeuristicResearchEventExtractor,
    ResearchEventFrame,
)
from personal_agent.application.research.service import canonicalize_url

from .dataset import (
    ResearchEventQualityRunOutput,
    build_research_event_quality_run_output,
    default_event_quality_cases_path,
    load_event_quality_cases,
)
from .scorer import score_event_quality_all


def fixture_generate_text(case):
    if not case.mock_understanding:
        return None

    def generate_text(prompt: str, name: str) -> str | None:
        if name == "research_request_understanding":
            return json.dumps(case.mock_understanding, ensure_ascii=False)
        return None

    return generate_text


class InMemoryResearchStore:
    def __init__(self) -> None:
        self.runs: dict[str, ResearchRun] = {}
        self.sources: dict[str, list[ResearchSource]] = {}
        self.events: dict[str, list[ResearchEvent]] = {}
        self.digests: dict[str, IntelligenceDigest] = {}
        self.subscriptions: dict[str, ResearchSubscription] = {}

    def create_run(self, run: ResearchRun) -> ResearchRun:
        self.runs[run.id] = run
        return run

    def update_run(self, run: ResearchRun) -> ResearchRun:
        self.runs[run.id] = run
        return run

    def get_run(self, run_id: str) -> ResearchRun | None:
        return self.runs.get(run_id)

    def get_subscription(
        self, subscription_id: str | None
    ) -> ResearchSubscription | None:
        return self.subscriptions.get(subscription_id or "")

    def replace_run_sources(
        self,
        run_id: str,
        sources: list[ResearchSource],
    ) -> None:
        self.sources[run_id] = list(sources)

    def list_run_sources(self, run_id: str) -> list[ResearchSource]:
        return list(self.sources.get(run_id, []))

    def replace_run_events(
        self,
        run_id: str,
        events: list[ResearchEvent],
    ) -> None:
        self.events[run_id] = list(events)

    def list_run_events(self, run_id: str) -> list[ResearchEvent]:
        return list(self.events.get(run_id, []))

    def list_recent_event_keys(self, user_id: str, since) -> set[str]:
        return set()

    def save_digest(self, digest: IntelligenceDigest) -> IntelligenceDigest:
        self.digests[digest.id] = digest
        return digest

    def get_digest(self, digest_id: str) -> IntelligenceDigest | None:
        return self.digests.get(digest_id)


class FixtureResearchTools:
    def __init__(self, case) -> None:
        self.case = case

    def __contains__(self, name: str) -> bool:
        return name in {"web_search", "capture_url", "graph_search"}

    def invoke_direct(self, name: str, **kwargs):
        if name == "web_search":
            query = str(kwargs.get("query") or "").lower()
            selected_results = list(self.case.search_results)
            for query_key, results in self.case.search_results_by_query.items():
                if query_key.lower() in query:
                    selected_results = list(results)
                    break
            return {
                "ok": True,
                "data": {"results": selected_results},
            }
        if name == "capture_url":
            url = str(kwargs.get("url") or "")
            content = (
                self.case.fulltext_by_url.get(url)
                or self.case.fulltext_by_url.get(canonicalize_url(url))
                or ""
            )
            return {"ok": True, "data": {"text": content}}
        if name == "graph_search":
            question = str(kwargs.get("question") or "").lower()
            matches: list[dict[str, object]] = []
            for title, title_matches in self.case.graph_matches_by_title.items():
                if title.lower() in question:
                    matches.extend(title_matches)
            return {"ok": True, "data": {"relation_facts": matches}}
        return {"ok": False, "error": "unsupported"}


class FixtureResearchEventExtractor:
    def __init__(self, case) -> None:
        self.case = case
        self.fallback = HeuristicResearchEventExtractor()

    def extract(self, sources, *, topic: str, instructions: str = ""):
        fallback_frames = self.fallback.extract(
            sources,
            topic=topic,
            instructions=instructions,
        )
        frames: dict[str, ResearchEventFrame] = {}
        for source in sources:
            raw = self.case.event_frames_by_title.get(source.title)
            if raw:
                frames[source.canonical_url] = ResearchEventFrame(
                    source_url=source.canonical_url,
                    title=source.title,
                    actor=str(raw.get("actor") or ""),
                    action=str(raw.get("action") or ""),
                    object=str(raw.get("object") or ""),
                    event_type=str(raw.get("event_type") or "unknown"),
                    occurred_at=str(raw.get("occurred_at") or ""),
                    entities=[
                        str(entity) for entity in raw.get("entities", [])
                    ],
                    confidence=float(raw.get("confidence", 0.0)),
                )
            else:
                frames[source.canonical_url] = fallback_frames[source.canonical_url]
        return frames


def test_research_event_quality_meets_baseline():
    cases = load_event_quality_cases(default_event_quality_cases_path())
    runs: dict[str, ResearchEventQualityRunOutput] = {}

    for case in cases:
        store = InMemoryResearchStore()
        service = ResearchService(
            store,
            FixtureResearchTools(case),
            generate_text=fixture_generate_text(case),
            event_extractor=FixtureResearchEventExtractor(case),
        )
        run = service.prepare_run(
            user_id=f"eval-{case.id}",
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
        (Path(__file__).parent / "event_quality_baseline.json").read_text(
            encoding="utf-8"
        )
    )
    failures = report.check_thresholds(baseline)
    assert not failures, f"regression:\n{report.summary()}\nfailures={failures}"
