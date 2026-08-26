from types import SimpleNamespace

from evals.product_baselines.test_investigation_consolidation_001 import (
    _provider_source_urls,
)
from evals.product_baselines.test_investigation_delegation_budget_001 import (
    _boundary_report,
)


class _RunStore:
    def __init__(self, records: dict[str, object]) -> None:
        self._records = records

    def get(self, execution_id: str):
        return self._records.get(execution_id)


def _run(agent_id: str, metadata: dict[str, object]):
    return SimpleNamespace(
        definition=SimpleNamespace(agent_id=agent_id),
        projection=SimpleNamespace(result={"metadata": metadata}),
    )


def test_provider_source_urls_use_only_canonical_gpt_researcher_results() -> None:
    store = _RunStore({
        "agent-run": _run(
            "gpt_researcher",
            {
                "source_urls": [
                    "https://modelcontextprotocol.io/specification",
                    {"url": "https://a2a-protocol.org/latest/"},
                ],
                "visited_urls": [
                    "https://modelcontextprotocol.io/specification",
                ],
            },
        ),
        "other-run": _run(
            "other_agent",
            {"source_urls": ["https://example.com/not-admissible"]},
        ),
    })

    urls = _provider_source_urls(
        store,  # type: ignore[arg-type]
        {
            "execution_refs": [
                {"execution_id": "agent-run"},
                {"execution_id": "other-run"},
                {"execution_id": "missing-run"},
            ]
        },
    )

    assert urls == (
        "https://a2a-protocol.org/latest/",
        "https://modelcontextprotocol.io/specification",
    )


def test_delegation_budget_grader_detects_project_token_and_cost_expansion() -> None:
    view = {
        "definition": {
            "budget": {
                "total_tokens": 80_000,
                "external_delegation_tokens": 20_000,
                "total_cost": 20.0,
            },
        },
        "accepted_execution_proposals": [
            {
                "proposal_id": "oversized-project-budget",
                "operation": {
                    "kind": "agent",
                    "token_budget": 24_000,
                    "cost_budget": 100_000.0,
                    "time_budget_seconds": 240,
                },
            },
        ],
        "commands": [],
        "execution_refs": [],
    }

    boundary = _boundary_report(view, max_runtime_seconds=240)

    assert boundary["oversized_runtime_proposals"] == ()
    assert len(boundary["oversized_project_budget_proposals"]) == 1
    assert boundary["oversized_proposals"]
