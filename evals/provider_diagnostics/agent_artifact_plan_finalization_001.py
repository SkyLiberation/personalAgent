"""Probe the existing FinalMessage plan-resolution contract on frozen artifacts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from evals.e2e_quality.trace_archive import archive_checksums_valid
from evals.product_baselines.evidence import canonical_evidence_digest
from evals.provider_diagnostics.interaction_intent_delegation_boundary_001 import (
    write_sealed_report,
)
from personal_agent.application.conversation.models import (
    ActionObservation,
    FinalMessage,
    InteractionTrace,
    ReviewCriteria,
)
from personal_agent.application.conversation.service import ConversationService
from personal_agent.application.conversation.working_plan import (
    admit_final_plan_resolution,
    incomplete_working_plan_feedback,
    is_terminal_working_plan,
)
from personal_agent.capabilities.contracts.model import StructuredModelClient
from personal_agent.infra.structured_model import build_structured_model_client
from personal_agent.kernel.config import Settings

_CASE_ID = "AGENT-ARTIFACT-PLAN-FINALIZATION-CONFORMANCE-001"
_REVISION = "agent-artifact-plan-finalization-conformance-v2"
_MARKER_PATTERN = re.compile(r"PERF-DELEGATE-\d{2}-7Q9X")
_URL_PATTERN = re.compile(r"https?://[^\s\]\[()\"'<>]+")


@dataclass(frozen=True, slots=True)
class FrozenFinalizationCase:
    repetition: int
    source_archive: Path
    source_checksum_digest: str
    marker: str
    observed_urls: tuple[str, ...]
    trace: InteractionTrace


def _successful_agent_artifacts(trace: InteractionTrace) -> tuple[ActionObservation, ...]:
    return tuple(
        item
        for item in trace.inputs
        if isinstance(item, ActionObservation)
        and item.kind == "agent_artifact"
        and item.status == "succeeded"
        and item.payload.get("status") in {"completed", "completed_degraded"}
    )


def _artifact_urls(artifacts: tuple[ActionObservation, ...]) -> tuple[str, ...]:
    urls: list[str] = []
    for observation in artifacts:
        payload_artifacts = observation.payload.get("artifacts", ())
        if not isinstance(payload_artifacts, (list, tuple)):
            continue
        for artifact in payload_artifacts:
            if not isinstance(artifact, dict):
                continue
            excerpt = artifact.get("content_excerpt")
            if not isinstance(excerpt, str):
                continue
            urls.extend(_URL_PATTERN.findall(excerpt))
    return tuple(dict.fromkeys(urls))


def load_frozen_cases(source_root: Path) -> tuple[FrozenFinalizationCase, ...]:
    cases: list[FrozenFinalizationCase] = []
    for trace_path in sorted(source_root.glob("**/*.trace.json")):
        archive = trace_path.parent
        if not archive_checksums_valid(archive):
            raise ValueError(f"source archive checksum is invalid: {archive}")
        document = json.loads(trace_path.read_text(encoding="utf-8"))
        report = document["trace"]
        interaction_trace = InteractionTrace.model_validate(
            report["interaction_trace"]
        )
        artifacts = _successful_agent_artifacts(interaction_trace)
        if report["result_metrics"]["delivered"] or not artifacts:
            continue
        marker_match = _MARKER_PATTERN.search(report["natural_user_text"])
        if marker_match is None:
            raise ValueError(f"source case has no public marker: {trace_path}")
        cases.append(
            FrozenFinalizationCase(
                repetition=int(report["repetition"]),
                source_archive=archive,
                source_checksum_digest=sha256(
                    (archive / "checksums.sha256").read_bytes()
                ).hexdigest(),
                marker=marker_match.group(0),
                observed_urls=_artifact_urls(artifacts),
                trace=interaction_trace,
            )
        )
    return tuple(sorted(cases, key=lambda case: case.repetition))


def evaluate_final_message(
    decision: FinalMessage,
    *,
    case: FrozenFinalizationCase,
) -> dict[str, Any]:
    working_plan = case.trace.working_plan
    if working_plan is None:
        raise ValueError("finalization conformance requires an admitted working plan")
    pending_ids = tuple(
        step.step_id for step in working_plan.steps if step.status == "pending"
    )
    exact_resolution_ids = (
        len(decision.resolved_plan_step_ids)
        == len(set(decision.resolved_plan_step_ids))
        and set(decision.resolved_plan_step_ids) == set(pending_ids)
    )
    feedback = None
    resolved_plan = None
    if decision.disposition == "answer":
        feedback, resolved_plan = admit_final_plan_resolution(
            decision.resolved_plan_step_ids,
            working_plan=working_plan,
            inputs=case.trace.inputs,
        )
    negative_control_rejected = None
    if pending_ids:
        negative_feedback, _ = admit_final_plan_resolution(
            (),
            working_plan=working_plan,
            inputs=case.trace.inputs,
        )
        negative_control_rejected = negative_feedback is not None
    admission_accepted = bool(
        decision.disposition == "answer"
        and feedback is None
        and resolved_plan is not None
        and is_terminal_working_plan(resolved_plan)
    )
    plan_resolution_contract_satisfied = bool(
        admission_accepted and exact_resolution_ids
    )
    if pending_ids:
        negative_control_ids: tuple[str, ...] = ()
    else:
        negative_control_ids = ("not-a-pending-step",)
    negative_feedback, _ = admit_final_plan_resolution(
        negative_control_ids,
        working_plan=working_plan,
        inputs=case.trace.inputs,
    )
    return {
        "expected_pending_plan_step_ids": list(pending_ids),
        "returned_resolved_plan_step_ids": list(decision.resolved_plan_step_ids),
        "exact_resolution_ids": exact_resolution_ids,
        "admission_accepted": admission_accepted,
        "plan_resolution_contract_satisfied": (
            plan_resolution_contract_satisfied
        ),
        "negative_control_empty_ids_rejected": negative_control_rejected,
        "negative_control_illegal_ids": list(negative_control_ids),
        "negative_control_illegal_ids_rejected": negative_feedback is not None,
        "output_has_public_marker": case.marker in decision.message,
        "output_has_observed_url": any(
            url in decision.message for url in case.observed_urls
        ),
        "observed_url_count": len(case.observed_urls),
    }


def run_conformance(
    model_client: StructuredModelClient,
    *,
    cases: tuple[FrozenFinalizationCase, ...],
    source_root: Path,
    config_cohort: dict[str, Any],
) -> dict[str, Any]:
    service = ConversationService(model_client)
    rows: list[dict[str, Any]] = []
    for case in cases:
        working_plan = case.trace.working_plan
        if working_plan is None:
            raise ValueError("frozen finalization case has no working plan")
        repair = incomplete_working_plan_feedback(working_plan)
        inputs = (
            case.trace.inputs + (repair,)
            if repair is not None
            else case.trace.inputs
        )
        try:
            decision, response = service._decide_answer_only(
                messages=case.trace.messages,
                inputs=inputs,
                review_criteria=case.trace.review_criteria or ReviewCriteria(),
                working_plan=working_plan,
            )
            evaluation = evaluate_final_message(decision, case=case)
            rows.append(
                {
                    "repetition": case.repetition,
                    "source_archive": case.source_archive.relative_to(
                        source_root
                    ).as_posix(),
                    "source_checksum_digest": case.source_checksum_digest,
                    "provider_error": None,
                    "repair_feedback_injected": repair is not None,
                    "decision": decision.model_dump(mode="json"),
                    "evaluation": evaluation,
                    "model_response": {
                        "model": response.model,
                        "latency_ms": response.latency_ms,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "total_tokens": response.total_tokens,
                        "retry_attempts": response.retry_attempts,
                    },
                }
            )
        except Exception as error:  # Preserve every frozen cohort member.
            rows.append(
                {
                    "repetition": case.repetition,
                    "source_archive": case.source_archive.relative_to(
                        source_root
                    ).as_posix(),
                    "source_checksum_digest": case.source_checksum_digest,
                    "provider_error": {
                        "type": type(error).__name__,
                        "message": str(error),
                    },
                    "repair_feedback_injected": repair is not None,
                    "decision": None,
                    "evaluation": None,
                    "model_response": None,
                }
            )

    evaluated = [row for row in rows if row["evaluation"] is not None]
    pending_rows = [
        row
        for row in evaluated
        if row["evaluation"]["expected_pending_plan_step_ids"]
    ]
    responses = [
        row["model_response"]
        for row in rows
        if row["model_response"] is not None
    ]
    provider_error_count = sum(row["provider_error"] is not None for row in rows)
    admission_accepted_count = sum(
        bool(row["evaluation"]["admission_accepted"])
        for row in evaluated
    )
    contract_satisfied_count = sum(
        bool(row["evaluation"]["plan_resolution_contract_satisfied"])
        for row in evaluated
    )
    negative_control_count = sum(
        bool(row["evaluation"]["negative_control_illegal_ids_rejected"])
        for row in evaluated
    )
    conformance_gate_passed = bool(
        rows
        and provider_error_count == 0
        and contract_satisfied_count == len(rows)
        and negative_control_count == len(rows)
    )
    return {
        "schema_version": 1,
        "case_id": _CASE_ID,
        "diagnostic_revision": _REVISION,
        "evidence_class": "runtime_provider_conformance_not_product_e2e",
        "production_contracts": [
            "interaction_completion_answer:v1",
            "FinalMessage.resolved_plan_step_ids",
            "admit_final_plan_resolution",
        ],
        "input_contract": {
            "source": "sealed_current_delegation_baseline_archives",
            "selection": "not delivered and succeeded AgentArtifact present",
            "repair": "existing working_plan_incomplete DecisionFeedback only",
            "automatic_plan_resolution": False,
        },
        "source_root": source_root.as_posix(),
        "source_case_digest": canonical_evidence_digest(
            [
                {
                    "repetition": case.repetition,
                    "source_checksum_digest": case.source_checksum_digest,
                }
                for case in cases
            ]
        ),
        "config_cohort": config_cohort,
        "config_cohort_digest": canonical_evidence_digest(config_cohort),
        "summary": {
            "sample_count": len(rows),
            "pending_plan_sample_count": len(pending_rows),
            "provider_error_count": provider_error_count,
            "admission_accepted_count": admission_accepted_count,
            "plan_resolution_contract_satisfied_count": contract_satisfied_count,
            "negative_control_illegal_ids_rejected_count": negative_control_count,
            "output_has_public_marker_count": sum(
                bool(row["evaluation"]["output_has_public_marker"])
                for row in evaluated
            ),
            "output_has_observed_url_count": sum(
                bool(row["evaluation"]["output_has_observed_url"])
                for row in evaluated
            ),
            "model_call_count": len(responses),
            "input_tokens": sum(int(item["input_tokens"] or 0) for item in responses),
            "output_tokens": sum(
                int(item["output_tokens"] or 0) for item in responses
            ),
            "total_tokens": sum(int(item["total_tokens"] or 0) for item in responses),
            "conformance_gate_passed": conformance_gate_passed,
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
        "operation": "interaction_completion_answer",
        "operation_version": "v1",
        "temperature": 0,
        "max_tokens": 3_200,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Probe whether the existing FinalMessage contract can explicitly resolve "
            "frozen pending plans after a successful AgentArtifact."
        )
    )
    parser.add_argument("source_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    cases = load_frozen_cases(args.source_root)
    if not cases:
        raise RuntimeError("no frozen completed-but-undelivered AgentArtifact cases found")
    settings = Settings.from_env()
    model_client = build_structured_model_client(
        settings.structured,
        settings.langsmith,
    )
    if model_client is None:
        raise RuntimeError("structured model provider is not configured")
    report = run_conformance(
        model_client,
        cases=cases,
        source_root=args.source_root,
        config_cohort=_config_cohort(settings),
    )
    checksum_path = write_sealed_report(report, args.output)
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    print(f"REPORT={args.output.resolve()}")
    print(f"CHECKSUMS={checksum_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
