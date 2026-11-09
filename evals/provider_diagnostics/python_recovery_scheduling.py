"""Zero-model, zero-create recovery scheduling over real sealed backend captures.

The public Conversation loop is not run. Its production accepted-request
recovery scheduler, executor, journal and capability projection are exercised
directly; SDK visibility remains a separate model-request checkpoint.
"""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import time
import zipfile

import docker

from evals.provider_diagnostics.python_execution_boundary import (
    BoundaryJourney,
    _checked,
    _require,
    _save,
)
from personal_agent.application.conversation.artifact_sources import trace_resource_refs
from personal_agent.application.conversation.journal import FileInteractionJournal
from personal_agent.application.conversation.model_actions import (
    build_model_action_definitions,
)
from personal_agent.application.conversation.models import (
    ActionObservation,
    InteractionTrace,
)
from personal_agent.application.conversation.service import ConversationService
from personal_agent.application.retrieval_experiment.service import (
    RetrievalExperimentService,
)
from personal_agent.infra.retrieval_experiment.backend import DockerExperimentBackend
from personal_agent.infra.retrieval_experiment.deployment import (
    LocalExperimentEnvironment,
)
from personal_agent.tools.retrieval_experiment import build_retrieval_experiment_tool

_BASE = Path(".tmp/python-analysis-implementation-20261021")
_SOURCE = Path(".tmp/context-compression-research-20261021/e1-preparation-3")


def _request_state(trace, action):
    accepted = next(
        item for item in trace.accepted_tool_requests if item.action_id == action
    )
    if accepted.tool_name == "execute_python":
        return accepted
    return next(item for item in trace.experiment_records if item.action_id == action)


def _recover(
    conversation: ConversationService, journal: FileInteractionJournal, action: str
):
    trace = journal.get("irun_retrieval_e1_20261020")
    inputs, usage, order = conversation._recover_accepted_requests(
        run_ref=trace.interaction_run_ref,
        principal=trace.principal,
        owner=trace.principal,
        conversation_id=trace.conversation_id,
        source_platform="offline_recovery_schedule",
        inputs=list(trace.inputs),
        usage=trace.usage,
        execution_order=list(trace.execution_order),
    )
    observed = [
        item
        for item in inputs
        if isinstance(item, ActionObservation) and item.action_id == action
    ]
    _require(
        len(observed) == 1,
        "recovery did not retain exactly one observation for the same accepted action",
    )
    latest = journal.get(trace.interaction_run_ref)
    _require(
        latest.usage == usage and latest.inputs == tuple(inputs),
        "recovery did not commit its real observation projection",
    )
    return latest, observed[0]


def _visible(
    conversation: ConversationService, trace: InteractionTrace
) -> dict[str, object]:
    capabilities = conversation._effective_capabilities(
        run_ref=trace.interaction_run_ref
    )
    visible = conversation._model_visible_capabilities_for_turn(
        capabilities, list(trace.inputs), run_ref=trace.interaction_run_ref
    )
    definitions = build_model_action_definitions(visible)
    return {
        "capabilities": [tool.name for tool in visible.tools],
        "action_names": [item.name for item in definitions],
        "action_definitions": [item.model_dump(mode="json") for item in definitions],
    }


def _case(
    journey: BoundaryJourney,
    root: Path,
    action: str,
    restore_capture,
    *,
    legacy_environment: LocalExperimentEnvironment | None = None,
):
    journal, artifacts, _, executor = journey._components(root)
    if legacy_environment is not None:
        experiments = RetrievalExperimentService(
            artifacts=artifacts,
            journal=journal,
            execution=DockerExperimentBackend(
                deployment=journey.deployment, environment=legacy_environment
            ),
            deployment=journey.deployment,
        )
        executor.register(build_retrieval_experiment_tool(experiments))
    conversation = ConversationService(
        None,
        tool_port=executor,
        artifact_port=artifacts,
        journal=journal,
        experiment_deployment=journey.deployment,
        experiment_model_capacity_valid=True,
    )
    initial = journal.get(journey.original_trace.interaction_run_ref)
    original = _request_state(initial, action)
    first, first_observation = _recover(conversation, journal, action)
    pending = _request_state(first, action)
    _require(
        pending.receipt is not None and pending.receipt.status == "unknown",
        "the actual missing backend did not produce unknown",
    )
    _require(
        first_observation.payload["data"]["receipt"]["status"] == "unknown",
        "unknown was not observed through the real Conversation executor",
    )
    before = _visible(conversation, first)
    budget_before = journal.execution_budget(first)
    _require(
        "execute_python" not in before["capabilities"]
        and action in budget_before.unsettled_action_ids,
        "unknown execution was exposed as settled or executable",
    )
    _save(
        root / "before-reconcile.json",
        {
            "trace_revision": first.revision,
            "usage": first.usage.model_dump(mode="json"),
            "budget": budget_before.model_dump(mode="json"),
            "observation": first_observation.model_dump(mode="json"),
            "capabilities": before,
        },
    )
    restore_capture()
    restored, terminal_observation = _recover(conversation, journal, action)
    terminal = _request_state(restored, action)
    after = _visible(conversation, restored)
    budget_after = journal.execution_budget(restored)
    _require(
        terminal.receipt is not None and terminal.receipt.status == "succeeded",
        f"original backend did not reconcile successfully: {terminal_observation.model_dump(mode='json')}",
    )
    _require(
        terminal.command == original.command
        and terminal.request_digest == original.request_digest,
        "recovery replaced the original command or request identity",
    )
    _require(
        restored.usage.tool_calls == first.usage.tool_calls
        and restored.usage == first.usage,
        "an already-observed reconciliation charged a new tool or model call",
    )
    _require(
        restored.execution_order == first.execution_order,
        "reconciliation created a second executed action",
    )
    _require(
        terminal_observation.status == "succeeded"
        and terminal_observation.payload["data"]["receipt"]["status"] == "succeeded",
        "the existing observation was not replaced by its actual terminal",
    )
    _require(
        action not in budget_after.unsettled_action_ids
        and budget_after.remaining_seconds > budget_before.remaining_seconds
        and "execute_python" in after["capabilities"],
        "actual terminal did not release reservation and restore current Python visibility",
    )
    original_snap = InteractionTrace.model_validate_json(
        (
            root
            / "data/interaction_runs"
            / first.interaction_run_ref
            / f"{first.revision:04d}.json"
        ).read_bytes()
    )
    old_observation = next(
        item
        for item in original_snap.inputs
        if isinstance(item, ActionObservation) and item.action_id == action
    )
    _require(
        old_observation.payload["data"]["receipt"]["status"] == "unknown",
        "append-only prior unknown observation was rewritten",
    )
    _save(
        root / "after-reconcile.json",
        {
            "trace_revision": restored.revision,
            "usage": restored.usage.model_dump(mode="json"),
            "budget": budget_after.model_dump(mode="json"),
            "observation": terminal_observation.model_dump(mode="json"),
            "capabilities": after,
            "command": terminal.command.model_dump(mode="json"),
            "execution": terminal.execution.model_dump(mode="json"),
            "receipt": terminal.receipt.model_dump(mode="json"),
        },
    )
    return {
        "action_id": action,
        "command_digest": terminal.command.command_digest,
        "request_digest": terminal.request_digest,
        "unknown_tool_calls": first.usage.tool_calls,
        "terminal_tool_calls": restored.usage.tool_calls,
        "released_reservation_seconds": budget_after.remaining_seconds
        - budget_before.remaining_seconds,
        "python_visible_before": False,
        "python_visible_after": True,
        "observation_replaced": True,
        "prior_unknown_snapshot_preserved": True,
    }


def run(output: Path) -> None:
    journey = BoundaryJourney(source=_BASE / "source-preflight.json", output=output)
    results: dict[str, object] = {}
    started = datetime.now(timezone.utc)
    original = _BASE / "boundary-20261021-a"
    source_hashes = {}
    # The prior sealed branch holds a real unknown Python receipt. Exclude the
    # separate refused follow-up action so this journey resumes only its owner.
    python = journey._branch(
        "p", copy_from=original / "unknown_missing_capture_and_job"
    )
    run_dir = (
        python / "data/interaction_runs" / journey.original_trace.interaction_run_ref
    )
    eligible = []
    for path in sorted(run_dir.glob("*.json")):
        trace = InteractionTrace.model_validate_json(path.read_bytes())
        if not any(
            item.action_id == "py-boundary-blocked-by-unknown"
            for item in trace.accepted_tool_requests
        ):
            eligible.append(path)
    cutoff = int(eligible[-1].stem)
    for path in run_dir.glob("*.json"):
        if int(path.stem) > cutoff:
            path.unlink()
    python_trace = InteractionTrace.model_validate_json(eligible[-1].read_bytes())
    python_command = _request_state(python_trace, "py-boundary-real-count").command
    python_capture = original / "success/jobs" / python_command.command_digest

    def restore_python():
        shutil.copytree(
            python_capture,
            python / "jobs" / python_command.command_digest,
            dirs_exist_ok=True,
        )

    with closing(
        docker.DockerClient(base_url=journey.endpoint, version="1.44", timeout=5)
    ) as client:
        client.api.trust_env = False
        results["python_observed_unknown"] = _case(
            journey, python, "py-boundary-real-count", restore_python
        )
        # Actual historical dispatching snapshot; no synthetic request, command
        # or receipt. A missing isolated backend naturally yields unknown first.
        historical = (
            _SOURCE
            / "server-data/interaction_runs"
            / journey.original_trace.interaction_run_ref
            / "0011.json"
        )
        legacy = InteractionTrace.model_validate_json(historical.read_bytes())
        legacy_record = next(
            item
            for item in legacy.experiment_records
            if item.command is not None and item.receipt is None
        )
        deployment = json.loads(
            (_SOURCE / "world/deployment.private.json").read_bytes()
        )
        environment = LocalExperimentEnvironment.model_validate(
            deployment["environment"]
        )
        old_backend = environment.workspace_root / legacy_record.command.command_digest
        if (old_backend / "execution.json").is_file() and (
            old_backend / "inputs.json"
        ).is_file():
            experiment = journey.output / "e"
            refs = set(trace_resource_refs(legacy))
            for item in journey.artifacts:
                if item.resource_ref not in refs:
                    continue
                folder = experiment / "data" / item.subdirectory
                folder.mkdir(parents=True, exist_ok=True)
                source_folder = (
                    Path(journey.preflight.artifact_roots["original"])
                    / item.subdirectory
                )
                data = _checked(
                    source_folder / item.storage_name, item.sha256, item.bytes
                )
                (folder / item.storage_name).write_bytes(data)
                shutil.copyfile(
                    source_folder / f"{item.resource_ref.resource_id}.json",
                    folder / f"{item.resource_ref.resource_id}.json",
                )
            mapped = legacy.model_copy(
                update={
                    "run_deadline_at": datetime.now(timezone.utc)
                    + timedelta(
                        seconds=journey.stage.remaining_at_input[
                            "wall_seconds_at_input"
                        ]
                    )
                }
            )
            _save(
                experiment
                / "data/interaction_runs"
                / mapped.interaction_run_ref
                / f"{mapped.revision:04d}.json",
                mapped,
            )
            for path in old_backend.rglob("*"):
                if path.is_file():
                    source_hashes[str(path)] = sha256(path.read_bytes()).hexdigest()
            clone_environment = environment.model_copy(
                update={"workspace_root": (experiment / "backend").resolve()}
            )

            def restore_experiment():
                shutil.copytree(
                    old_backend,
                    clone_environment.workspace_root
                    / legacy_record.command.command_digest,
                )

            results["retrieval_observed_unknown"] = _case(
                journey,
                experiment,
                legacy_record.action_id,
                restore_experiment,
                legacy_environment=clone_environment,
            )
            results["retrieval_source"] = {
                "journal": str(historical),
                "sha256": sha256(historical.read_bytes()).hexdigest(),
                "backend_source": str(old_backend),
                "original_refs": len(refs),
                "classification": "Actual dispatching checkpoint; isolated missing-backend counterfactual generates unknown through the real service, followed by same-command actual terminal capture",
            }
        else:
            results["retrieval_observed_unknown"] = {
                "status": "not_covered",
                "reason": "same-command actual backend capture unavailable",
            }
        events = list(
            client.events(
                since=int(started.timestamp()),
                until=int(time.time()) + 1,
                decode=True,
                filters={"type": "container", "event": "create"},
            )
        )
        _require(not events, "recovery scheduling created a container")
        _save(journey.output / "docker-create-events.json", events)
    for path, digest in source_hashes.items():
        _require(
            sha256(Path(path).read_bytes()).hexdigest() == digest,
            "original retrieval backend was modified",
        )
    _require(
        journey.source_hashes == journey._source_hashes(),
        "production identity changed during the diagnostic",
    )
    _save(
        journey.output / "recovery-scheduling-report.json",
        {
            "results": results,
            "model_calls": 0,
            "new_containers": 0,
            "evidence_class": "Offline real-source Conversation recovery-scheduler boundary",
            "limitations": [
                "No full respond/model loop",
                "No actual SDK request or physical model send; capability/action definition projection only",
                "Historical deadline mapped only in isolated copy",
                "Fault injected by initially missing copied backend; no live process crash",
                "Initial sealed evidence remains read-only",
            ],
        },
    )
    (journey.output / "recovery-scheduling-report.md").write_text(
        "# Conversation恢复调度Offline检查\n\n实际调用ConversationService的接受请求恢复调度、原ToolExecutor、FileJournal及执行服务；无Fake、模型调用或新容器。\n\nPython与原BM25实验均先通过缺失后端的隔离边界产生实际unknown观察，再导入同Command的原真实终态捕获。已有观察被替换，原Command／请求／执行顺序保持，tool_calls不增加；预留释放，当前Python可见性恢复。历史unknown快照保持。\n\n这只覆盖恢复调度与当前能力／动作投影；没有调用完整respond循环或发送SDK请求，不把它写成模型实际见到工具。首轮while每轮重算的位置经源码review，后续实际SDK仍由局部组核对。原历史资料与早期封存目录只读，所有故障与恢复状态只写本次复制分支。\n",
        encoding="utf-8",
    )
    with zipfile.ZipFile(
        journey.output / "exact-source-snapshot.zip",
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for path, digest in journey.source_hashes.items():
            data = Path(path).read_bytes()
            _require(
                sha256(data).hexdigest() == digest, "source changed before sealing"
            )
            archive.writestr(path.replace("\\", "/"), data)
        archive.write(
            __file__, "evals/provider_diagnostics/python_recovery_scheduling.py"
        )
    manifest = {
        str(path.relative_to(journey.output)): sha256(path.read_bytes()).hexdigest()
        for path in journey.output.rglob("*")
        if path.is_file()
    }
    _save(journey.output / "checksums.json", manifest)
    print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
