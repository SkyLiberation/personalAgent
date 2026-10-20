"""Replay AUD-001's complete real run at the formal HTTP scope boundary."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import time

import httpx

from evals.e2e_quality.test_policy_audit_isolation import (
    AuditOutcome,
    HttpFact,
    KEYS,
    OTHER,
    PolicyRow,
    audit_process,
)
from evals.e2e_quality.trace_archive import TraceArchive, archive_checksums_valid
from personal_agent.application.conversation.models import InteractionTrace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_archive.resolve()
    if not archive_checksums_valid(source):
        raise ValueError("source E2E archive checksum is invalid")
    envelope = json.loads(
        next(source.glob("AUD-001.*.trace.json")).read_text(encoding="utf-8")
    )
    owner_fact = next(
        fact
        for fact in envelope["trace"]["facts"]
        if "/conversation/runs/" in fact["path"] and fact["caller"] == "owner"
    )
    actual = InteractionTrace.model_validate(owner_fact["payload"])
    journal = source / "primary-data/interaction_runs"
    snapshots = {
        path.relative_to(journal).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in journal.rglob("*.json")
    }
    latest = max(journal.rglob("*.json"), key=lambda path: int(path.stem))
    if InteractionTrace.model_validate_json(latest.read_bytes()) != actual:
        raise ValueError("source Journal does not match the sealed actual HTTP run")
    archive = TraceArchive(
        args.output_root.resolve(),
        manifest_metadata={
            "evidence_class": "boundary_evaluation",
            "source_archive": str(source),
            "model_calls_planned": 0,
        },
    )
    outcome = AuditOutcome()
    node = "evals/e2e_quality/policy_audit_replay.py::main"
    started = time.monotonic()
    passed = False
    detail = None
    try:
        with audit_process(archive, journal_snapshot=journal) as server:
            restored = archive.run_dir / "primary-data/interaction_runs"
            if snapshots != {
                path.relative_to(restored).as_posix(): sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in restored.rglob("*.json")
            }:
                raise ValueError("real Journal restoration changed bytes")
            archive.update_environment(
                {"sample_plan": {"stage_replay": 1}, "source_journal_sha256": snapshots}
            )
            with httpx.Client(timeout=20) as client:

                def call(path, caller, **kwargs):
                    response = client.get(
                        server.base_url + path,
                        headers={"Authorization": "Bearer " + KEYS[caller]},
                        **kwargs,
                    )
                    fact = HttpFact(
                        method="GET",
                        path=path,
                        caller=caller,
                        status=response.status_code,
                        payload=response.json(),
                    )
                    outcome.facts.append(fact)
                    return fact

                run = actual.interaction_run_ref
                owner = call("/primary/api/conversation/runs/" + run, "owner")
                outcome.owner_read_allowed = (
                    owner.status == 200
                    and InteractionTrace.model_validate(owner.payload) == actual
                )
                query = "/api/audit/policy-decisions"
                params = {"run_id": run, "action": "conversation_trace_read"}
                initial = call("/primary" + query, "admin", params=params)
                outcome.owner_read_denials = (
                    len(initial.payload["items"]) if initial.status == 200 else None
                )
                outcome.foreign_read_rejected = (
                    call("/primary/api/conversation/runs/" + run, "other").status == 404
                )
                outcome.ordinary_audit_rejected = (
                    call("/primary" + query, "other", params=params).status == 403
                )
                primary = call("/primary" + query, "admin", params=params)
                secondary = call("/secondary" + query, "admin", params=params)
                if primary.status != 200 or secondary.status != 200:
                    raise ValueError("administrator query failed")
                outcome.primary_denials = [
                    PolicyRow.model_validate(item) for item in primary.payload["items"]
                ]
                outcome.secondary_denials = [
                    PolicyRow.model_validate(item)
                    for item in secondary.payload["items"]
                ]
                expected = PolicyRow(
                    action="conversation_trace_read",
                    effect="deny",
                    rule="conversation_run_scope_mismatch",
                    user_id=OTHER.principal_id,
                    resource=run,
                    run_id=run,
                )
                outcome.audit_isolated = (
                    outcome.primary_denials == [expected]
                    and not outcome.secondary_denials
                )
                if not (
                    outcome.owner_read_allowed
                    and outcome.owner_read_denials == 0
                    and outcome.foreign_read_rejected
                    and outcome.ordinary_audit_rejected
                    and outcome.audit_isolated
                ):
                    raise ValueError("real-stage scope/audit counterfactual failed")
        log = (archive.run_dir / "server.log").read_text(encoding="utf-8")
        if "chat/completions" in log or "/embeddings" in log:
            raise ValueError("scope-only replay unexpectedly called a model")
        passed = True
    except BaseException as exc:
        outcome.failure_category = type(exc).__name__
        detail = str(exc)
        raise
    finally:
        outcome.duration_seconds = round(time.monotonic() - started, 3)
        archive.write_trace(
            nodeid=node,
            case_id="AUD-001-REPLAY",
            trace={
                "source_e2e_archive": str(source),
                "source_run": actual.interaction_run_ref,
                "source_journal_sha256": snapshots,
                "original_product_result": "failed",
                "new_model_calls": 0,
                "checkpoint_passed": passed,
                "outcome": outcome.model_dump(mode="json"),
            },
        )
        archive.record_test_result(
            nodeid=node,
            phase="call",
            outcome="passed" if passed else "failed",
            duration_seconds=outcome.duration_seconds,
            detail=detail,
        )
        archive.finalize(exit_status=0 if passed else 1)
        print(
            json.dumps(
                {
                    "archive": str(archive.run_dir),
                    "checkpoint_passed": passed,
                    "model_calls": 0,
                    "seconds": outcome.duration_seconds,
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
