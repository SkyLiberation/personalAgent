"""Interleave control and contrast intent prompts in one provider time window."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from math import ceil
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from urllib.parse import urlparse

from evals.product_baselines.evidence import canonical_evidence_digest
from evals.product_baselines.test_agent_perf_delegate_001 import (
    delegation_request_text,
)
from evals.provider_diagnostics.interaction_intent_delegation_boundary_001 import (
    write_sealed_report,
)
from personal_agent.application.conversation.interaction_intent import (
    _DERIVATION_INSTRUCTION,
    InteractionIntentProposal,
    admit_interaction_intent,
)
from personal_agent.application.conversation.models import ConversationMessage
from personal_agent.capabilities.contracts.model import (
    StructuredModelClient,
    StructuredModelRequest,
    sealed_context_projection_ref,
)
from personal_agent.infra.structured_model import build_structured_model_client
from personal_agent.kernel.config import Settings

_CASE_ID = "INTERACTION-INTENT-CONTRAST-INTERLEAVED-001"
_REVISION = "interaction-intent-contrast-interleaved-v2"
_CONTRAST_SUFFIX = (
    " Boundary examples: asking to delegate an independent specialist and then "
    "synthesize that specialist's result in the current response is foreground, so "
    "return false. Asking work to continue after the current response and to be "
    "queried, paused, resumed, or steered in a later interaction is background "
    "continuation, so return true with the exact proving substring."
)

Arm = Literal["control", "contrast"]


def _p95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return ordered[ceil(0.95 * len(ordered)) - 1]


def _invoke(
    model_client: StructuredModelClient,
    *,
    arm: Arm,
    request_text: str,
) -> dict[str, Any]:
    instruction = (
        _DERIVATION_INSTRUCTION
        if arm == "control"
        else _DERIVATION_INSTRUCTION + _CONTRAST_SUFFIX
    )
    messages = [
        {"role": "system", "content": instruction},
        ConversationMessage(role="user", content=request_text).model_dump(mode="json"),
    ]
    started = perf_counter()
    response = model_client.generate(
        StructuredModelRequest(
            operation="interaction_intent",
            version="v2",
            messages=messages,
            output_type=InteractionIntentProposal,
            context_projection_ref=sealed_context_projection_ref(
                purpose="interaction_intent_contrast_interleaved_conformance",
                messages=messages,
            ),
            temperature=0,
            max_tokens=800,
            metadata={
                "component": "interaction_intent_contrast_interleaved_diagnostic",
            },
        )
    )
    wall_seconds = perf_counter() - started
    admitted = admit_interaction_intent(
        response.value,
        messages=(ConversationMessage(role="user", content=request_text),),
    )
    return {
        "arm": arm,
        "wall_seconds": round(wall_seconds, 6),
        "provider_latency_ms": response.latency_ms,
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "total_tokens": response.total_tokens,
        "retry_attempts": response.retry_attempts,
        "proposal": response.value.model_dump(mode="json"),
        "admitted": admitted.model_dump(mode="json"),
        "misclassified_as_background": admitted.background_continuation_requested,
    }


def compare(
    model_client: StructuredModelClient,
    *,
    request_text: str,
    pairs: int,
    config_cohort: dict[str, Any],
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    provider_errors: list[dict[str, Any]] = []
    for pair in range(1, pairs + 1):
        order: tuple[Arm, Arm] = (
            ("control", "contrast")
            if pair % 2
            else ("contrast", "control")
        )
        for position, arm in enumerate(order, start=1):
            try:
                row = _invoke(
                    model_client,
                    arm=arm,
                    request_text=request_text,
                )
                row.update({"pair": pair, "position": position})
                samples.append(row)
            except Exception as error:  # Preserve the complete interleaved cohort.
                provider_errors.append(
                    {
                        "pair": pair,
                        "position": position,
                        "arm": arm,
                        "type": type(error).__name__,
                        "message": str(error),
                    }
                )

    summaries: dict[str, dict[str, Any]] = {}
    for arm in ("control", "contrast"):
        arm_rows = [row for row in samples if row["arm"] == arm]
        latencies = [float(row["wall_seconds"]) for row in arm_rows]
        summaries[arm] = {
            "sample_count": len(arm_rows),
            "misclassified_as_background_count": sum(
                bool(row["misclassified_as_background"]) for row in arm_rows
            ),
            "wall_seconds_p95": round(_p95(latencies), 6) if latencies else None,
            "wall_seconds_maximum": round(max(latencies), 6) if latencies else None,
            "input_tokens": sum(int(row["input_tokens"] or 0) for row in arm_rows),
            "output_tokens": sum(int(row["output_tokens"] or 0) for row in arm_rows),
            "total_tokens": sum(int(row["total_tokens"] or 0) for row in arm_rows),
        }
    paired_latency_deltas: list[float] = []
    for pair in range(1, pairs + 1):
        pair_rows = [row for row in samples if row["pair"] == pair]
        if {row["arm"] for row in pair_rows} == {"control", "contrast"}:
            by_arm = {str(row["arm"]): row for row in pair_rows}
            paired_latency_deltas.append(
                float(by_arm["contrast"]["wall_seconds"])
                - float(by_arm["control"]["wall_seconds"])
            )
    return {
        "schema_version": 1,
        "case_id": _CASE_ID,
        "diagnostic_revision": _REVISION,
        "evidence_class": "provider_conformance_not_product_e2e",
        "production_contract": "interaction_intent:v2:first_proposal",
        "isolated_variable": "system_instruction_contrast_suffix",
        "control_instruction_digest": canonical_evidence_digest(
            _DERIVATION_INSTRUCTION
        ),
        "contrast_instruction_digest": canonical_evidence_digest(
            _DERIVATION_INSTRUCTION + _CONTRAST_SUFFIX
        ),
        "input_digest": canonical_evidence_digest(request_text),
        "config_cohort": config_cohort,
        "config_cohort_digest": canonical_evidence_digest(config_cohort),
        "pair_count": pairs,
        "provider_errors": provider_errors,
        "summary": {
            "provider_error_count": len(provider_errors),
            "control": summaries["control"],
            "contrast": summaries["contrast"],
            "paired_latency_delta_seconds": {
                "minimum": round(min(paired_latency_deltas), 6)
                if paired_latency_deltas
                else None,
                "p95": round(_p95(paired_latency_deltas), 6)
                if paired_latency_deltas
                else None,
                "maximum": round(max(paired_latency_deltas), 6)
                if paired_latency_deltas
                else None,
            },
        },
        "samples": samples,
    }


def _config_cohort(settings: Settings) -> dict[str, Any]:
    return {
        "structured_model": settings.structured.model,
        "structured_provider_host": urlparse(settings.structured.base_url or "").hostname,
        "structured_output_transport": settings.structured.output_transport,
        "structured_timeout_seconds": settings.structured.timeout_seconds,
        "structured_max_retries": settings.structured.max_retries,
        "operation": "interaction_intent",
        "operation_version": "v2",
        "temperature": 0,
        "max_tokens": 800,
        "order": "odd control-first; even contrast-first",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Interleave control and contrast intent prompts in one time window."
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("--pairs", type=int, default=20)
    parser.add_argument("--source-repetition", type=int, default=16)
    args = parser.parse_args()
    if not 1 <= args.pairs <= 20:
        parser.error("--pairs must be between 1 and 20")
    if not 1 <= args.source_repetition <= 20:
        parser.error("--source-repetition must be between 1 and 20")

    settings = Settings.from_env()
    model_client = build_structured_model_client(
        settings.structured,
        settings.langsmith,
    )
    if model_client is None:
        raise RuntimeError("structured model provider is not configured")
    report = compare(
        model_client,
        request_text=delegation_request_text(args.source_repetition),
        pairs=args.pairs,
        config_cohort=_config_cohort(settings),
    )
    checksum_path = write_sealed_report(report, args.output)
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    print(f"REPORT={args.output.resolve()}")
    print(f"CHECKSUMS={checksum_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
