"""Measure explicit foreground delegation versus background-continuation intent."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from evals.product_baselines.evidence import canonical_evidence_digest
from evals.product_baselines.test_agent_perf_delegate_001 import (
    delegation_request_text,
)
from personal_agent.application.conversation.interaction_intent import (
    derive_interaction_intent,
)
from personal_agent.application.conversation.models import ConversationMessage
from personal_agent.capabilities.contracts.model import StructuredModelClient
from personal_agent.infra.structured_model import build_structured_model_client
from personal_agent.kernel.config import Settings

_CASE_ID = "INTERACTION-INTENT-DELEGATION-BOUNDARY-001"
_DIAGNOSTIC_REVISION = "interaction-intent-delegation-boundary-v1"


def diagnose(
    model_client: StructuredModelClient,
    *,
    requests: Sequence[tuple[int, str]],
    config_cohort: dict[str, Any],
    input_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the production intent derivation without executing the proposed work."""
    rows: list[dict[str, Any]] = []
    for repetition, request_text in requests:
        started = perf_counter()
        try:
            admitted, responses, feedback = derive_interaction_intent(
                model_client,
                messages=(ConversationMessage(role="user", content=request_text),),
            )
            rows.append({
                "repetition": repetition,
                "natural_user_text": request_text,
                "expected_delivery_boundary": "foreground_current_response",
                "duration_seconds": round(perf_counter() - started, 6),
                "provider_error": None,
                "model_responses": [
                    {
                        "model": response.model,
                        "latency_ms": response.latency_ms,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "total_tokens": response.total_tokens,
                        "retry_attempts": response.retry_attempts,
                        "proposal": response.value.model_dump(mode="json"),
                    }
                    for response in responses
                ],
                "admitted": admitted.model_dump(mode="json"),
                "feedback": [item.model_dump(mode="json") for item in feedback],
                "misclassified_as_background": (
                    admitted.background_continuation_requested
                ),
            })
        except Exception as error:  # Diagnostic must preserve every cohort member.
            rows.append({
                "repetition": repetition,
                "natural_user_text": request_text,
                "expected_delivery_boundary": "foreground_current_response",
                "duration_seconds": round(perf_counter() - started, 6),
                "provider_error": {
                    "type": type(error).__name__,
                    "message": str(error),
                },
                "model_responses": [],
                "admitted": None,
                "feedback": [],
                "misclassified_as_background": False,
            })

    misclassified = [
        int(row["repetition"])
        for row in rows
        if row["misclassified_as_background"]
    ]
    provider_errors = [
        int(row["repetition"])
        for row in rows
        if row["provider_error"] is not None
    ]
    model_responses = [
        response
        for row in rows
        for response in row["model_responses"]
    ]
    return {
        "schema_version": 1,
        "case_id": _CASE_ID,
        "diagnostic_revision": _DIAGNOSTIC_REVISION,
        "evidence_class": "provider_diagnostic_not_product_e2e",
        "production_contract": "derive_interaction_intent:interaction_intent:v2",
        "input_contract": input_contract or {"mode": "provided_requests"},
        "input_digest": canonical_evidence_digest([
            {"repetition": repetition, "text": text}
            for repetition, text in requests
        ]),
        "config_cohort": config_cohort,
        "config_cohort_digest": canonical_evidence_digest(config_cohort),
        "summary": {
            "sample_count": len(rows),
            "misclassified_as_background_count": len(misclassified),
            "misclassified_repetitions": misclassified,
            "provider_error_count": len(provider_errors),
            "provider_error_repetitions": provider_errors,
            "model_call_count": len(model_responses),
            "input_tokens": sum(
                int(item["input_tokens"] or 0) for item in model_responses
            ),
            "output_tokens": sum(
                int(item["output_tokens"] or 0) for item in model_responses
            ),
            "total_tokens": sum(
                int(item["total_tokens"] or 0) for item in model_responses
            ),
        },
        "samples": rows,
    }


def write_sealed_report(report: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    output_path.write_bytes(encoded)
    checksum_path = output_path.parent / "checksums.sha256"
    checksum_path.write_text(
        f"{sha256(encoded).hexdigest()} *{output_path.name}\n",
        encoding="utf-8",
    )
    return checksum_path


def _config_cohort(settings: Settings) -> dict[str, Any]:
    return {
        "structured_model": settings.structured.model,
        "structured_provider_host": urlparse(
            settings.structured.base_url or ""
        ).hostname,
        "structured_output_transport": settings.structured.output_transport,
        "structured_timeout_seconds": settings.structured.timeout_seconds,
        "structured_max_retries": settings.structured.max_retries,
        "operation": "interaction_intent",
        "operation_version": "v2",
        "temperature": 0,
        "max_tokens": 800,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure whether explicit foreground delegation is proposed as unsupported "
            "background continuation by the production intent derivation."
        )
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument(
        "--repeat-request",
        type=int,
        default=None,
        help="Repeat one canonical cohort request instead of rotating all requests.",
    )
    args = parser.parse_args()
    if not 1 <= args.samples <= 20:
        parser.error("--samples must be between 1 and 20")
    if args.repeat_request is not None and not 1 <= args.repeat_request <= 20:
        parser.error("--repeat-request must be between 1 and 20")

    settings = Settings.from_env()
    model_client = build_structured_model_client(
        settings.structured,
        settings.langsmith,
    )
    if model_client is None:
        raise RuntimeError("structured model provider is not configured")
    requests = tuple(
        (
            repetition,
            delegation_request_text(args.repeat_request or repetition),
        )
        for repetition in range(1, args.samples + 1)
    )
    input_contract = (
        {
            "mode": "repeated_canonical_request",
            "source_repetition": args.repeat_request,
            "sample_count": args.samples,
        }
        if args.repeat_request is not None
        else {
            "mode": "rotating_canonical_cohort",
            "sample_count": args.samples,
        }
    )
    report = diagnose(
        model_client,
        requests=requests,
        config_cohort=_config_cohort(settings),
        input_contract=input_contract,
    )
    checksum_path = write_sealed_report(report, args.output)
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    print(f"REPORT={args.output.resolve()}")
    print(f"CHECKSUMS={checksum_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
