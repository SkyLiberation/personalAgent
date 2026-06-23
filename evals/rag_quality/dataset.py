"""Dataset model + loader for the RAG-quality harness.

A case is a question plus *annotations*: the gold-relevant evidence ids (for
retrieval metrics), an optional reference answer (for generation metrics), and
optional per-claim gold verdicts (for grounding metrics).

``RunOutput`` is the thin, scoreable projection of a pipeline run — ranked /
selected evidence ids, the answer, and the verifier's claim verdicts. The
scorer only ever sees a ``RunOutput``, so it stays decoupled from the heavy
``AskRunContext`` and is trivially unit-testable with hand-built fixtures.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RagEvalCase:
    id: str
    question: str
    # Gold-relevant evidence ids (note id / chunk id / fact id / url).
    gold_evidence_ids: list[str] = field(default_factory=list)
    reference_answer: str = ""
    # Optional per-claim gold verdicts, aligned to the answer's extracted
    # claims in order: "supported" | "contradicted" | "not_found".
    gold_claim_verdicts: list[str] = field(default_factory=list)
    # How many of this case's claims genuinely need counter-evidence (for
    # contrastive coverage). 0 means the answer is one-sided-by-design.
    claims_needing_contrast: int = 0
    requires_graph_evidence: bool = False
    description: str = ""


@dataclass
class RunOutput:
    """Scoreable projection of one pipeline run."""

    # Evidence ids in recall order (full pool), best-first.
    ranked_evidence_ids: list[str] = field(default_factory=list)
    # Evidence ids selected into the prompt context pack.
    selected_evidence_ids: list[str] = field(default_factory=list)
    # Text of the selected evidence (for faithfulness scoring).
    selected_evidence_texts: list[str] = field(default_factory=list)
    answer: str = ""
    # Verifier per-claim verdict statuses, in claim order.
    claim_verdicts: list[str] = field(default_factory=list)
    # Counter-evidence items found for contradicted/missing claims.
    counter_evidence_found: int = 0
    # Retrieval source label aligned with ranked_evidence_ids (e.g. graphiti/local).
    retrieval_sources: list[str] = field(default_factory=list)
    # End-to-end and LLM efficiency telemetry for the case.
    latency_ms: float = 0.0
    llm_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


def load_cases(path: str | Path) -> list[RagEvalCase]:
    """Load cases from a JSON array file. Unknown keys are ignored so the
    dataset file can carry human-facing notes without breaking the loader."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    fields = RagEvalCase.__dataclass_fields__.keys()
    cases: list[RagEvalCase] = []
    for entry in raw:
        kwargs = {k: v for k, v in entry.items() if k in fields}
        cases.append(RagEvalCase(**kwargs))
    return cases


def default_cases_path() -> Path:
    return Path(__file__).parent / "cases.json"
