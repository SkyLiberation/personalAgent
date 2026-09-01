"""Probe the production working-plan tool schema against the configured provider."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from evals.provider_diagnostics.interaction_intent_delegation_boundary_001 import (
    write_sealed_report,
)
from personal_agent.application.conversation.model_actions import (
    build_model_action_definitions,
    decode_model_action_invocations,
)
from personal_agent.application.conversation.models import (
    ContinueTurnProposal,
    EffectiveCapabilities,
)
from personal_agent.capabilities.contracts.model import (
    ModelActionDefinition,
    ModelInvocationUnavailable,
    StructuredModelClient,
    StructuredModelRequest,
    StructuredOutputFailure,
    sealed_context_projection_ref,
)
from personal_agent.infra.structured_model import build_structured_model_client
from personal_agent.kernel.config import Settings

_CASE_ID = "WORKING-PLAN-TOOL-SCHEMA-CONFORMANCE-001"
_REVISION = "working-plan-tool-schema-conformance-v2"
_OPERATION = "working_plan_tool_schema_conformance"
_MAX_TOKENS = 600
_MESSAGES = [
    {
        "role": "system",
        "content": (
            "Call the only available action exactly once. Create a concise two-step "
            "working plan. Use the schema exactly; do not add undeclared fields."
        ),
    },
    {
        "role": "user",
        "content": (
            "Plan how to compare two official protocol documents and then write a "
            "short conclusion. Do not execute the plan."
        ),
    },
]


class _UnusedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _working_plan_definition() -> ModelActionDefinition:
    definitions = build_model_action_definitions(EffectiveCapabilities())
    matches = tuple(
        definition
        for definition in definitions
        if definition.kind == "working_plan"
    )
    if len(matches) != 1:
        raise RuntimeError("expected exactly one production working-plan definition")
    return matches[0]


def _schema_digest(definition: ModelActionDefinition) -> str:
    encoded = json.dumps(
        definition.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _request(definition: ModelActionDefinition) -> StructuredModelRequest[_UnusedOutput]:
    return StructuredModelRequest(
        operation=_OPERATION,
        version="v1",
        messages=_MESSAGES,
        output_type=_UnusedOutput,
        context_projection_ref=sealed_context_projection_ref(
            purpose=_OPERATION,
            messages=_MESSAGES,
        ),
        temperature=0,
        max_tokens=_MAX_TOKENS,
        kind="tool_calling",
        action_definitions=(definition,),
        action_choice="required",
    )


def _failure(error: Exception) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": type(error).__name__,
        "message": str(error),
    }
    if isinstance(error, StructuredOutputFailure):
        result.update({
            "reason_code": error.reason_code,
            "action_name": error.action_name,
            "action_kind": error.action_kind,
            "field_paths": list(error.field_paths),
            "error_types": list(error.error_types),
        })
    elif isinstance(error, ModelInvocationUnavailable):
        result.update({
            "category": error.category,
            "provider_host": error.provider_host,
            "status_code": error.status_code,
            "retryable": error.retryable,
        })
    return result


def run_conformance(
    model_client: StructuredModelClient,
    *,
    samples: int,
    config_cohort: dict[str, Any],
) -> dict[str, Any]:
    if samples < 1 or samples > 10:
        raise ValueError("samples must be between 1 and 10")
    definition = _working_plan_definition()
    request = _request(definition)
    rows: list[dict[str, Any]] = []
    for repetition in range(1, samples + 1):
        try:
            response = model_client.generate(request)
            decision = decode_model_action_invocations(
                response.action_invocations,
                (definition,),
            )
            valid = bool(
                isinstance(decision, ContinueTurnProposal)
                and decision.working_plan is not None
                and not decision.actions
            )
            rows.append({
                "repetition": repetition,
                "valid_working_plan_payload": valid,
                "action_invocation_count": len(response.action_invocations),
                "failure": None,
                "model_response": {
                    "model": response.model,
                    "latency_ms": response.latency_ms,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "total_tokens": response.total_tokens,
                    "retry_attempts": response.retry_attempts,
                },
            })
        except Exception as error:  # Preserve every predeclared sample.
            rows.append({
                "repetition": repetition,
                "valid_working_plan_payload": False,
                "action_invocation_count": 0,
                "failure": _failure(error),
                "model_response": None,
            })

    valid_count = sum(row["valid_working_plan_payload"] for row in rows)
    provider_failure_count = sum(
        bool(
            row["failure"]
            and row["failure"]["type"] == "ModelInvocationUnavailable"
        )
        for row in rows
    )
    schema_failure_count = sum(
        bool(
            row["failure"]
            and row["failure"]["type"] == "StructuredOutputFailure"
        )
        for row in rows
    )
    responses = [
        row["model_response"]
        for row in rows
        if row["model_response"] is not None
    ]
    return {
        "schema_version": 1,
        "case_id": _CASE_ID,
        "diagnostic_revision": _REVISION,
        "evidence_class": "provider_conformance_not_product_e2e",
        "production_contracts": [
            "control_working_plan action definition",
            "flat WorkingPlanProposal control payload",
            "WorkingPlanProposal strict schema",
            "decode_model_action_invocations",
        ],
        "input_contract": {
            "same_request_for_every_sample": True,
            "business_tools_exposed": 0,
            "external_tool_calls": 0,
            "database_writes": 0,
            "sample_count": samples,
            "max_tokens_per_sample": _MAX_TOKENS,
        },
        "action_definition": {
            "name": definition.name,
            "kind": definition.kind,
            "strict": True,
            "schema_digest": _schema_digest(definition),
        },
        "config_cohort": config_cohort,
        "summary": {
            "sample_count": samples,
            "valid_working_plan_payload_count": valid_count,
            "provider_failure_count": provider_failure_count,
            "schema_failure_count": schema_failure_count,
            "model_call_count": len(responses),
            "input_tokens": sum(int(item["input_tokens"] or 0) for item in responses),
            "output_tokens": sum(
                int(item["output_tokens"] or 0) for item in responses
            ),
            "total_tokens": sum(int(item["total_tokens"] or 0) for item in responses),
            "conformance_gate_passed": valid_count == samples,
        },
        "samples": rows,
    }


def _config_cohort(settings: Settings) -> dict[str, Any]:
    return {
        "structured_model": settings.structured.model,
        "structured_provider_host": urlparse(
            settings.structured.base_url or ""
        ).hostname,
        "structured_output_transport": settings.structured.output_transport,
        "structured_timeout_seconds": settings.structured.timeout_seconds,
        "structured_max_retries": settings.structured.max_retries,
        "operation": _OPERATION,
        "operation_version": "v1",
        "temperature": 0,
        "max_tokens": _MAX_TOKENS,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure whether the configured provider obeys the production "
            "control_working_plan strict tool schema."
        )
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("--samples", type=int, default=3)
    args = parser.parse_args()

    settings = Settings.from_env()
    model_client = build_structured_model_client(
        settings.structured,
        settings.langsmith,
    )
    if model_client is None:
        raise RuntimeError("structured model provider is not configured")
    report = run_conformance(
        model_client,
        samples=args.samples,
        config_cohort=_config_cohort(settings),
    )
    checksum_path = write_sealed_report(report, args.output)
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    print(f"REPORT={args.output.resolve()}")
    print(f"CHECKSUMS={checksum_path.resolve()}")
    return 0 if report["summary"]["conformance_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
