"""Real-environment runner for the RAG-quality golden set.

The offline gate (test_rag_quality_gate.py) feeds hand-built reference evidence
through the real verifier — the verdict logic is real, but retrieval and
generation are NOT exercised. This runner closes that gap: it builds a real
``AgentService`` from ``Settings.from_env()``, seeds each case's reference
evidence as real notes, runs the real ``execute_ask`` pipeline (retrieve →
generate → verify) end to end, and projects the result into the same
``RunOutput`` the offline scorer already consumes.

Honest caveats (why this is a scaffold, not yet a full real golden set):
  - The bundled cases use synthetic evidence ids (n1/n2). To make retrieval
    scoring meaningful against a real store, each case's reference evidence is
    seeded as real notes under a *case-scoped user*, and gold ids are remapped
    to the seeded note ids. This measures "can the real retriever surface the
    right seeded notes for this question", not performance over your real
    corpus — that needs real captured notes (currently empty).
  - Requires a configured LLM (OPENAI_* / answer generation) AND Postgres.
    ``build_real_service`` returns None when either is missing so the gate skips
    rather than fails. This runner produces the real-environment Golden result.
"""

from __future__ import annotations

from time import perf_counter

from personal_agent.orchestration.service import AgentService
from personal_agent.infra.runtime_llm import LlmClient
from personal_agent.kernel.config import Settings
from personal_agent.kernel.llm_telemetry import collect_llm_usage

from .dataset import RagEvalCase, RunOutput
from .runner import run_output_from_result


def build_real_service() -> AgentService | None:
    """Build a real AgentService from env, or None when LLM/Postgres unconfigured."""
    try:
        settings = Settings.from_env()
    except Exception:
        return None
    if not settings.postgres_url:
        return None
    if not LlmClient(settings)._configured():
        return None
    try:
        return AgentService(settings)
    except Exception:
        return None


def seed_case_notes(service: AgentService, case: RagEvalCase, reference: dict) -> dict[str, str]:
    """Seed a case's reference evidence as real notes under a case-scoped user.

    Returns a {synthetic_gold_id -> seeded_note_id} remap so the scorer can
    compare real retrieval against the actually-seeded notes.
    """
    user_id = f"rag-eval-{case.id}"
    id_map: dict[str, str] = {}
    for item in reference.get("evidence", []):
        synthetic_id = str(item.get("source_id", ""))
        title = str(item.get("title", "") or synthetic_id)
        snippet = str(item.get("snippet", "") or "")
        result = service.execute_capture(
            text=f"{title}\n\n{snippet}",
            source_type="text",
            user_id=user_id,
        )
        if synthetic_id:
            id_map[synthetic_id] = result.note.id
    if case.requires_graph_evidence and id_map:
        sync_results = service.sync_notes_to_graph(list(id_map.values()))
        failed = [note_id for note_id, ok in sync_results.items() if not ok]
        if failed:
            raise RuntimeError(
                f"{case.id}: graph-required seed notes failed to sync: {failed}"
            )
    return id_map


def ask_case(service: AgentService, case: RagEvalCase) -> RunOutput:
    """Run the real ask pipeline for a case and project to a RunOutput."""
    started = perf_counter()
    with collect_llm_usage() as usage:
        result = service.execute_ask(
            case.question,
            f"rag-eval-{case.id}",
            f"rag-eval-{case.id}",
        )
    output = run_output_from_result(result)
    output.latency_ms = round((perf_counter() - started) * 1000, 2)
    output.llm_call_count = usage.call_count
    output.input_tokens = usage.input_tokens
    output.output_tokens = usage.output_tokens
    output.total_tokens = usage.total_tokens
    return output
