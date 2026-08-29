from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Literal

import pytest

from evals.e2e_quality.trace_archive import TraceArchive
from evals.product_baselines.evidence import (
    EvidencePairError,
    ProductEvidenceIdentity,
    canonical_evidence_digest,
    validate_product_evidence_pair,
)
from personal_agent.application.conversation.models import (
    CommittedUsage,
    ConversationMessage,
    FinalMessage,
    InteractionTrace,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


def test_trace_archive_persists_outcome_summary_and_checksums(temp_dir) -> None:
    archive = TraceArchive(
        temp_dir,
        run_id="evidence-run",
        manifest_metadata={"structured_model": "test-model"},
    )
    trace_path = archive.write_trace(
        nodeid="evals/test_live.py::test_case",
        case_id="case-one",
        trace={"input": {"text": "hello"}, "output": {"run_status": "completed"}},
    )
    archive.record_test_result(
        nodeid="evals/test_live.py::test_case",
        phase="call",
        outcome="passed",
        duration_seconds=1.25,
    )
    archive.record_test_result(
        nodeid="evals/test_live.py::test_failed_before_trace",
        phase="call",
        outcome="failed",
        duration_seconds=0.5,
        detail="planner rejected the live plan",
    )

    summary_path = archive.finalize(exit_status=0)

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads((archive.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert trace["test_outcome"] == "passed"
    assert summary["counts"]["passed"] == 1
    assert summary["counts"]["failed"] == 1
    by_nodeid = {item["nodeid"]: item for item in summary["tests"]}
    assert by_nodeid["evals/test_live.py::test_case"]["trace_files"] == [trace_path.name]
    failed = by_nodeid["evals/test_live.py::test_failed_before_trace"]
    assert failed["trace_files"] == []
    assert failed["phases"]["call"]["detail"] == "planner rejected the live plan"
    assert manifest["environment"]["structured_model"] == "test-model"

    checksums = {}
    for line in (archive.run_dir / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        digest, filename = line.split("  ", maxsplit=1)
        checksums[filename] = digest
    for path in archive.run_dir.glob("*.json"):
        assert checksums[path.name] == sha256(path.read_bytes()).hexdigest()


def test_atomic_write_uses_a_short_temporary_basename(temp_dir, monkeypatch) -> None:
    final_path = temp_dir / ("promotion-decision-" + "x" * 80 + ".trace.json")
    observed: list[Path] = []
    original_write_bytes = Path.write_bytes

    def recording_write_bytes(path: Path, data: bytes) -> int:
        observed.append(path)
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", recording_write_bytes)

    TraceArchive._atomic_write(final_path, b"sealed")

    assert final_path.read_bytes() == b"sealed"
    temporary, = observed
    assert temporary.parent == final_path.parent
    assert temporary.name.startswith(".tmp-")
    assert len(temporary.name) < len(final_path.name)
    assert not temporary.exists()


def test_trace_archive_automatically_extracts_typed_interaction_measurement(
    temp_dir,
) -> None:
    archive = TraceArchive(temp_dir, run_id="automatic-measurement")
    interaction = InteractionTrace(
        interaction_run_ref="irun_measurement",
        conversation_id="conversation-measurement",
        principal=AuthenticatedPrincipal(tenant_id="tenant-1", user_id="user-1"),
        messages=(ConversationMessage(role="user", content="answer this"),),
        usage=CommittedUsage(
            model_turns=2,
            tool_calls=1,
            agent_calls=0,
            total_tokens=120,
        ),
        final_message=FinalMessage(disposition="answer", message="done"),
    )

    path = archive.write_trace(
        nodeid="evals/e2e_quality/test_case.py::test_case",
        case_id="case.product_http",
        trace={"path_evidence": {"interaction": interaction.model_dump(mode="json")}},
    )

    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["measurement"] == {
        "agent_calls": 0,
        "input_tokens": None,
        "limited": False,
        "model_calls": None,
        "model_turns": 2,
        "output_tokens": None,
        "recovery_duration_seconds": None,
        "replay_new_side_effects": None,
        "tool_calls": 1,
        "total_tokens": 120,
    }


def _write_product_archive(
    output_root,
    *,
    run_id: str,
    role: Literal["baseline", "target"],
    user_input: str = "same user request",
    config_cohort: str,
):
    archive = TraceArchive(output_root, run_id=run_id)
    nodeid = "evals/product_baselines/test_case.py::test_case"
    archive.write_trace(
        nodeid=nodeid,
        case_id="PAIR-001",
        trace={"user_visible_result": "done"},
        product_evidence=ProductEvidenceIdentity(
            case_id="PAIR-001",
            role=role,
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            principal=AuthenticatedPrincipal(
                tenant_id="tenant-1",
                user_id="user-1",
            ),
            user_input_digest=canonical_evidence_digest(user_input),
            initial_state_digest=canonical_evidence_digest({"seed": "fixed"}),
            config_cohort=config_cohort,
            grader_version="pair-001-v1",
        ),
    )
    archive.record_test_result(
        nodeid=nodeid,
        phase="call",
        outcome="passed",
        duration_seconds=0.1,
    )
    archive.finalize(exit_status=0)
    return archive.run_dir


def test_product_target_runs_do_not_modify_sealed_baseline(temp_dir) -> None:
    baseline_dir = _write_product_archive(
        temp_dir,
        run_id="baseline-run",
        role="baseline",
        config_cohort="baseline-config",
    )
    baseline_checksum = sha256(
        (baseline_dir / "checksums.sha256").read_bytes()
    ).hexdigest()

    first_target = _write_product_archive(
        temp_dir,
        run_id="target-run-1",
        role="target",
        config_cohort="target-config",
    )
    second_target = _write_product_archive(
        temp_dir,
        run_id="target-run-2",
        role="target",
        config_cohort="target-config",
    )

    assert first_target != second_target
    assert sha256(
        (baseline_dir / "checksums.sha256").read_bytes()
    ).hexdigest() == baseline_checksum
    validate_product_evidence_pair(baseline_dir, first_target)
    validate_product_evidence_pair(baseline_dir, second_target)


def test_product_evidence_pair_rejects_different_user_input(temp_dir) -> None:
    baseline_dir = _write_product_archive(
        temp_dir,
        run_id="baseline-mismatch",
        role="baseline",
        config_cohort="baseline-config",
    )
    target_dir = _write_product_archive(
        temp_dir,
        run_id="target-mismatch",
        role="target",
        user_input="different user request",
        config_cohort="target-config",
    )

    with pytest.raises(EvidencePairError, match="user_input_digest"):
        validate_product_evidence_pair(baseline_dir, target_dir)


def test_product_evidence_pair_rejects_same_code_and_config(temp_dir) -> None:
    baseline_dir = _write_product_archive(
        temp_dir,
        run_id="baseline-same-subject",
        role="baseline",
        config_cohort="same-config",
    )
    target_dir = _write_product_archive(
        temp_dir,
        run_id="target-same-subject",
        role="target",
        config_cohort="same-config",
    )

    with pytest.raises(EvidencePairError, match="same code and configuration"):
        validate_product_evidence_pair(baseline_dir, target_dir)
