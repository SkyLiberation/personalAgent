"""Real LLM gate for Research request understanding.

This gate evaluates the model-facing part of ``initialize_state``: converting a
raw natural-language research request into topic, instructions, policy, max
items and query-plan intents. It intentionally stops before search/cluster/digest
so failures are attributable to request understanding rather than providers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from personal_agent.application.research import ResearchService
from personal_agent.infra.runtime_llm import LlmClient
from personal_agent.infra.structured_model import build_chat_model_client
from personal_agent.kernel.config import Settings

from .test_research_event_quality_gate import InMemoryResearchStore
from .understanding_dataset import (
    ResearchUnderstandingRunOutput,
    load_understanding_cases,
    run_output_from_state,
)
from .understanding_scorer import score_understanding_all


class _NoopResearchTools:
    def __contains__(self, name: str) -> bool:
        return False

    def invoke_direct(self, name: str, **kwargs):
        return {"ok": False, "error": "unsupported"}


def test_real_llm_research_request_understanding_meets_baseline():
    settings = Settings.from_env()
    if not (settings.openai.api_key and settings.openai.base_url):
        pytest.skip("OpenAI-compatible LLM config is not configured.")
    client = build_chat_model_client(settings.openai, settings.langsmith)
    if client is None:
        pytest.skip("Chat model client is not configured.")
    llm = LlmClient(settings, model_client=client)
    cases = load_understanding_cases()
    outputs: dict[str, ResearchUnderstandingRunOutput] = {}

    for case in cases:
        store = InMemoryResearchStore()
        service = ResearchService(
            store,
            _NoopResearchTools(),
            generate_text=lambda prompt, name: llm.generate_answer(
                prompt,
                prompt_name=name,
            ),
        )
        run = service.prepare_run(
            user_id=f"understanding-eval-{case.id}",
            topic=case.raw_request,
            max_items=case.default_max_items,
        )
        state = service.initialize_state(run.id)
        outputs[case.id] = run_output_from_state(state)

    report = score_understanding_all(cases, outputs)
    baseline = json.loads(
        (Path(__file__).parent / "understanding_baseline.json").read_text(
            encoding="utf-8"
        )
    )
    failures = report.check_thresholds(baseline)
    assert not failures, f"regression:\n{report.summary()}\nfailures={failures}"
